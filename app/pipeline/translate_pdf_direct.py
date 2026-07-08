from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import fitz  # PyMuPDF

from app.pipeline.block_schema import ExtractedTextBlock
from app.pipeline.extract_native_blocks import (
    collect_language_detection_samples,
    extract_pdf_metadata_language,
    extract_native_text_blocks,
)
from app.pipeline.fonts import resolve_font_for_text
from app.pipeline.pdf_content_policy import ensure_pdf_translation_allowed
from app.pipeline.translate_pdf_image_text import translate_pdf_image_text
from app.pipeline.translator_factory import get_translator
from app.pipeline.translator_llm import should_retry_translation


@dataclass(frozen=True)
class DirectTranslationStats:
    blocks_total: int
    blocks_translated: int
    blocks_skipped: int
    blocks_retried: int
    blocks_rejected: int
    api_calls: int
    source_lang: str
    # Layout-fit accounting (subset of blocks_translated): a translation that did not
    # fit its box was either truncated with an ellipsis ("truncated") or could not be
    # placed at all after the source was redacted ("dropped" = silent content loss).
    blocks_truncated: int = 0
    blocks_dropped: int = 0
    image_regions_processed: int = 0
    image_blocks_translated: int = 0
    image_blocks_rejected: int = 0
    image_api_calls: int = 0


def _capture_page_links(page: fitz.Page) -> list[dict]:
    captured: list[dict] = []
    for link in page.get_links():
        link_copy = dict(link)
        if "from" in link_copy and isinstance(link_copy["from"], fitz.Rect):
            rect = link_copy["from"]
            link_copy["from"] = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y1)
        captured.append(link_copy)
    return captured


def _restore_page_links(page: fitz.Page, links: list[dict]) -> None:
    seen: set[tuple] = set()
    for link in links:
        if "from" not in link:
            continue
        rect = link["from"]
        key = (
            round(rect.x0, 2),
            round(rect.y0, 2),
            round(rect.x1, 2),
            round(rect.y1, 2),
            link.get("kind"),
            link.get("uri"),
            link.get("page"),
        )
        if key in seen:
            continue
        seen.add(key)

        payload = {k: v for k, v in link.items() if k in {"kind", "from", "uri", "page", "to", "file", "name", "zoom"}}
        try:
            page.insert_link(payload)
        except Exception:
            continue


def _is_display_block(block: ExtractedTextBlock) -> bool:
    return block.kind == "title" or block.style.font_size >= 36.0


def _fit_and_write_block(page: fitz.Page, block: ExtractedTextBlock, translated: str) -> str:
    """Render ``translated`` into ``block``'s box.

    Returns one of: ``"fit"`` (placed in full), ``"truncated"`` (placed but clipped
    with an ellipsis — text lost), ``"dropped"`` (source redacted but nothing could be
    placed — total content loss), or ``"skipped"`` (degenerate/empty box, source left
    untouched).
    """
    rect = fitz.Rect(*block.bbox)
    if rect.width < 3 or rect.height < 3:
        return "skipped"

    text = re.sub(r"\s*\n+\s*", " ", translated).strip()
    if not text:
        return "skipped"

    display_block = _is_display_block(block)
    if display_block:
        extra_width = 0.0
        min_h = rect.height
    elif block.kind in {"abstract"}:
        height_factor = max(2.8, 1.1 + (block.line_count * 1.1))
        extra_width = min(20.0, max(0.0, block.style.font_size * 1.1))
        min_h = max(rect.height, block.style.font_size * height_factor)
    elif block.kind in {"caption", "reference", "table"}:
        height_factor = max(1.8, 0.95 + (block.line_count * 0.95))
        extra_width = min(6.0, max(0.0, block.style.font_size * 0.25))
        min_h = max(rect.height, block.style.font_size * height_factor)
    elif block.kind == "paragraph":
        height_factor = max(2.4, 1.15 + (block.line_count * 1.02))
        extra_width = min(14.0, max(0.0, block.style.font_size * 0.75))
        min_h = max(rect.height, block.style.font_size * height_factor)
    else:
        height_factor = max(1.45, 0.9 + (block.line_count * 0.7))
        extra_width = min(10.0, max(0.0, block.style.font_size * 0.5))
        min_h = max(rect.height, block.style.font_size * height_factor)

    if block.column_index is not None and not display_block:
        extra_width = min(extra_width, 6.0)
        min_h *= 1.18

    max_x1 = min(page.rect.x1 - 2.0, rect.x1 + extra_width)
    rect = fitz.Rect(rect.x0, rect.y0, max_x1, rect.y0 + min_h)

    # Remove source text in this line box while preserving images / line art / background.
    page.add_redact_annot(rect, fill=None)
    page.apply_redactions(
        images=getattr(fitz, "PDF_REDACT_IMAGE_NONE", 0),
        graphics=getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0),
        text=getattr(fitz, "PDF_REDACT_TEXT_REMOVE", 0),
    )

    fontname, fontfile, render_text = resolve_font_for_text(page, block.style, text)
    if display_block:
        size = max(8.0, block.style.font_size)
        line_height = 1.05 if block.kind == "title" else 1.08
    elif block.kind in {"caption", "reference", "table"}:
        size = max(6.0, min(block.style.font_size, 18.0))
        line_height = 1.06
    elif block.kind in {"paragraph", "abstract"}:
        size = max(6.5, min(block.style.font_size, 28.0))
        line_height = 1.18
    else:
        size = max(6.5, min(block.style.font_size, 28.0))
        line_height = 1.12

    for _ in range(10):
        spare = page.insert_textbox(
            rect,
            render_text,
            fontname=fontname,
            fontfile=fontfile,
            fontsize=size,
            color=block.style.color_rgb,
            align=fitz.TEXT_ALIGN_LEFT,
            lineheight=line_height,
            overlay=True,
        )
        if spare >= -0.5:
            return "fit"
        size *= 0.92

    # Last fallback to avoid complete miss.
    clipped = render_text[: max(1, int(len(render_text) * 0.72))].rstrip() + "…"
    spare = page.insert_textbox(
        rect,
        clipped,
        fontname=fontname,
        fontfile=fontfile,
        fontsize=max(6.0, size),
        color=block.style.color_rgb,
        align=fitz.TEXT_ALIGN_LEFT,
        lineheight=1.08,
        overlay=True,
    )
    snippet = text[:60] + ("…" if len(text) > 60 else "")
    if spare >= -3.0:
        print(
            f"⚠️  block {block.block_id} ({block.kind}) p{block.page_index + 1}: "
            f"translation too long for its box — TRUNCATED to fit (text lost): {snippet!r}"
        )
        return "truncated"
    print(
        f"⚠️  block {block.block_id} ({block.kind}) p{block.page_index + 1}: "
        f"translation could not be placed after redaction — DROPPED (content lost): {snippet!r}"
    )
    return "dropped"


def translate_pdf_direct(
    pdf_in: Path,
    pdf_out: Path,
    target_lang: str,
    source_lang: Optional[str] = None,
    translate_image_text: bool = False,
    engine: Optional[str] = None,
) -> DirectTranslationStats:
    ensure_pdf_translation_allowed(pdf_in)
    blocks = extract_native_text_blocks(pdf_in)
    if not blocks:
        raise RuntimeError("No translatable text lines found in PDF.")

    translator = get_translator(engine)
    if source_lang is None:
        samples = collect_language_detection_samples(blocks)
        metadata_language = extract_pdf_metadata_language(pdf_in)
        source_lang = translator.detect_language(samples, metadata_language=metadata_language)
        print(f"Detected source language: {source_lang}")

    if source_lang == target_lang:
        raise ValueError(f"Source and target language are the same ({source_lang}).")

    translated_map: Dict[int, str] = {}
    api_calls = 0
    retried = 0
    rejected = 0

    for i, block in enumerate(blocks, start=1):
        if i % 25 == 0 or i == len(blocks):
            print(f"Translating lines: {i}/{len(blocks)}")
        candidate = translator.translate_single_strict(block.text, source_lang, target_lang)
        api_calls += 1
        if not candidate:
            rejected += 1
            continue
        candidate = re.sub(r"\s*\n+\s*", " ", candidate).strip()

        if len(block.text.strip()) > 16 and should_retry_translation(
            block.text, candidate, source_lang, target_lang
        ):
            retry = translator.translate_single_strict(block.text, source_lang, target_lang)
            api_calls += 1
            retried += 1
            if not retry:
                rejected += 1
                continue
            retry = re.sub(r"\s*\n+\s*", " ", retry).strip()
            if should_retry_translation(block.text, retry, source_lang, target_lang):
                rejected += 1
                continue
            candidate = retry

        translated_map[block.block_id] = candidate

    doc = fitz.open(str(pdf_in))
    page_links = {page_index: _capture_page_links(page) for page_index, page in enumerate(doc)}
    image_stats = None
    try:
        translated_count = 0
        truncated_count = 0
        dropped_count = 0
        for block in blocks:
            translated = translated_map.get(block.block_id)
            if not translated:
                continue
            page = doc[block.page_index]
            status = _fit_and_write_block(page, block, translated)
            if status in ("fit", "truncated"):
                translated_count += 1
            if status == "truncated":
                truncated_count += 1
            elif status == "dropped":
                dropped_count += 1
        if translate_image_text:
            print("Translating text embedded in images...")
            image_stats = translate_pdf_image_text(
                doc,
                source_lang=source_lang,
                target_lang=target_lang,
                engine=engine,
            )
        for page_index, page in enumerate(doc):
            _restore_page_links(page, page_links.get(page_index, []))
        pdf_out.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(pdf_out), garbage=3, deflate=True)
    finally:
        doc.close()

    print(f"Retried suspicious lines: {retried} (rejected: {rejected})")
    if truncated_count or dropped_count:
        print(
            f"⚠️  Layout fit: {truncated_count} block(s) truncated, "
            f"{dropped_count} block(s) dropped (translation longer than the original box)."
        )
    total = len(blocks)
    return DirectTranslationStats(
        blocks_total=total,
        blocks_translated=translated_count,
        blocks_skipped=total - translated_count,
        blocks_retried=retried,
        blocks_rejected=rejected,
        api_calls=api_calls,
        source_lang=source_lang,
        blocks_truncated=truncated_count,
        blocks_dropped=dropped_count,
        image_regions_processed=image_stats.image_regions_processed if image_stats else 0,
        image_blocks_translated=image_stats.image_blocks_translated if image_stats else 0,
        image_blocks_rejected=image_stats.image_blocks_rejected if image_stats else 0,
        image_api_calls=image_stats.api_calls if image_stats else 0,
    )
