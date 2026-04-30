from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import fitz  # PyMuPDF

from app.pipeline.block_schema import ExtractedTextBlock
from app.pipeline.extract_native_blocks import (
    collect_language_detection_samples,
    extract_native_text_blocks,
)
from app.pipeline.fonts import resolve_font_for_text
from app.pipeline.translate_pdf_image_text import translate_pdf_image_text
from app.pipeline.translator_llm import LLMTranslator, should_retry_translation


@dataclass(frozen=True)
class DirectTranslationStats:
    blocks_total: int
    blocks_translated: int
    blocks_skipped: int
    blocks_retried: int
    blocks_rejected: int
    api_calls: int
    source_lang: str
    image_regions_processed: int = 0
    image_blocks_translated: int = 0
    image_blocks_rejected: int = 0
    image_api_calls: int = 0

def _fit_and_write_block(page: fitz.Page, block: ExtractedTextBlock, translated: str) -> bool:
    rect = fitz.Rect(*block.bbox)
    if rect.width < 3 or rect.height < 3:
        return False

    text = re.sub(r"\s*\n+\s*", " ", translated).strip()
    if not text:
        return False

    if block.kind in {"title", "abstract"}:
        height_factor = 2.6
        extra_width = min(28.0, max(0.0, block.style.font_size * 1.5))
    elif block.kind in {"caption", "reference", "table"}:
        height_factor = 1.65
        extra_width = min(10.0, max(0.0, block.style.font_size * 0.4))
    elif block.kind == "paragraph":
        height_factor = 2.2
        extra_width = min(24.0, max(0.0, block.style.font_size * 1.2))
    else:
        height_factor = 1.35
        extra_width = min(16.0, max(0.0, block.style.font_size * 0.8))

    min_h = max(rect.height, block.style.font_size * height_factor)
    rect = fitz.Rect(rect.x0, rect.y0, rect.x1 + extra_width, rect.y0 + min_h)

    # Remove source text in this line box while preserving images / line art / background.
    page.add_redact_annot(rect, fill=None)
    page.apply_redactions(
        images=getattr(fitz, "PDF_REDACT_IMAGE_NONE", 0),
        graphics=getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0),
        text=getattr(fitz, "PDF_REDACT_TEXT_REMOVE", 0),
    )

    fontname, fontfile = resolve_font_for_text(page, block.style, text)
    if block.kind == "title":
        size = max(8.0, min(block.style.font_size, 32.0))
        line_height = 1.1
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
            text,
            fontname=fontname,
            fontfile=fontfile,
            fontsize=size,
            color=block.style.color_rgb,
            align=fitz.TEXT_ALIGN_LEFT,
            lineheight=line_height,
            overlay=True,
        )
        if spare >= -0.5:
            return True
        size *= 0.92

    # Last fallback to avoid complete miss.
    clipped = text[: max(1, int(len(text) * 0.72))].rstrip() + "…"
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
    return spare >= -3.0


def translate_pdf_direct(
    pdf_in: Path,
    pdf_out: Path,
    target_lang: str,
    source_lang: Optional[str] = None,
    translate_image_text: bool = False,
) -> DirectTranslationStats:
    blocks = extract_native_text_blocks(pdf_in)
    if not blocks:
        raise RuntimeError("No translatable text lines found in PDF.")

    translator = LLMTranslator()
    if source_lang is None:
        samples = collect_language_detection_samples(blocks)
        source_lang = translator.detect_language(samples)
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
    image_stats = None
    try:
        translated_count = 0
        for block in blocks:
            translated = translated_map.get(block.block_id)
            if not translated:
                continue
            page = doc[block.page_index]
            if _fit_and_write_block(page, block, translated):
                translated_count += 1
        if translate_image_text:
            print("Translating text embedded in images...")
            image_stats = translate_pdf_image_text(
                doc,
                source_lang=source_lang,
                target_lang=target_lang,
            )
        pdf_out.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(pdf_out), garbage=3, deflate=True)
    finally:
        doc.close()

    print(f"Retried suspicious lines: {retried} (rejected: {rejected})")
    total = len(blocks)
    return DirectTranslationStats(
        blocks_total=total,
        blocks_translated=translated_count,
        blocks_skipped=total - translated_count,
        blocks_retried=retried,
        blocks_rejected=rejected,
        api_calls=api_calls,
        source_lang=source_lang,
        image_regions_processed=image_stats.image_regions_processed if image_stats else 0,
        image_blocks_translated=image_stats.image_blocks_translated if image_stats else 0,
        image_blocks_rejected=image_stats.image_blocks_rejected if image_stats else 0,
        image_api_calls=image_stats.api_calls if image_stats else 0,
    )
