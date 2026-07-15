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
from app.pipeline.protected_text import (
    contains_protected_token,
    has_unprotected_translatable_text,
    is_contact_identity_text,
    protect_nontranslatable_text,
    restore_protected_text,
)
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
    # Layout-fit accounting. If a translation cannot be placed in a readable size,
    # the source text is preserved and the block is counted as unplaced.
    blocks_truncated: int = 0
    blocks_unplaced: int = 0
    # Backward-compatible field; new code should not drop content after redaction.
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


def _link_key(link: dict) -> tuple | None:
    rect = link.get("from")
    if rect is None:
        return None
    rect = fitz.Rect(rect)
    return (
        round(rect.x0, 2),
        round(rect.y0, 2),
        round(rect.x1, 2),
        round(rect.y1, 2),
        link.get("kind"),
        link.get("uri"),
        link.get("page"),
    )


def _restore_page_links(page: fitz.Page, links: list[dict]) -> None:
    seen: set[tuple] = {
        key for link in page.get_links() if (key := _link_key(link)) is not None
    }
    for link in links:
        if "from" not in link:
            continue
        key = _link_key(link)
        if key is None or key in seen:
            continue
        seen.add(key)

        payload = {k: v for k, v in link.items() if k in {"kind", "from", "uri", "page", "to", "file", "name", "zoom"}}
        try:
            page.insert_link(payload)
        except Exception:
            continue


def _is_display_block(block: ExtractedTextBlock) -> bool:
    return block.kind == "title" or block.style.font_size >= 36.0


def _redaction_rect_avoiding(
    source_rect: fitz.Rect,
    avoid_rects: list[fitz.Rect],
) -> fitz.Rect:
    rect = fitz.Rect(source_rect)
    for avoid in avoid_rects:
        avoid = fitz.Rect(avoid)
        horizontal_overlap = min(rect.x1, avoid.x1) - max(rect.x0, avoid.x0)
        vertical_overlap = min(rect.y1, avoid.y1) - max(rect.y0, avoid.y0)
        if horizontal_overlap <= 0 or vertical_overlap <= 0:
            continue

        horizontal_ratio = horizontal_overlap / max(1.0, min(rect.width, avoid.width))
        vertical_ratio = vertical_overlap / max(1.0, min(rect.height, avoid.height))
        gap = 0.25
        if horizontal_ratio >= 0.25:
            if rect.y0 < avoid.y0 < rect.y1:
                rect.y1 = min(rect.y1, avoid.y0 - gap)
            elif rect.y0 < avoid.y1 < rect.y1:
                rect.y0 = max(rect.y0, avoid.y1 + gap)
        elif vertical_ratio >= 0.25:
            if rect.x0 < avoid.x0 < rect.x1:
                rect.x1 = min(rect.x1, avoid.x0 - gap)
            elif rect.x0 < avoid.x1 < rect.x1:
                rect.x0 = max(rect.x0, avoid.x1 + gap)

    return rect


def _same_rect(a: fitz.Rect, b: fitz.Rect, tolerance: float = 0.5) -> bool:
    return (
        abs(a.x0 - b.x0) <= tolerance
        and abs(a.y0 - b.y0) <= tolerance
        and abs(a.x1 - b.x1) <= tolerance
        and abs(a.y1 - b.y1) <= tolerance
    )


def _overlap_amount(a0: float, a1: float, b0: float, b1: float) -> float:
    return min(a1, b1) - max(a0, b0)


def _candidate_layout_rects(
    page: fitz.Page,
    block: ExtractedTextBlock,
    source_rect: fitz.Rect,
    base_rect: fitz.Rect,
    obstacle_rects: list[fitz.Rect],
) -> list[fitz.Rect]:
    candidates = [fitz.Rect(base_rect)]
    display_block = _is_display_block(block)
    if display_block or block.kind != "line" or source_rect.width >= 220:
        return candidates

    margin = 2.0
    gap = 2.0
    left = page.rect.x0 + margin
    right = page.rect.x1 - margin

    for obstacle in obstacle_rects:
        obstacle = fitz.Rect(obstacle)
        if _same_rect(source_rect, obstacle):
            continue
        vertical_overlap = _overlap_amount(source_rect.y0, source_rect.y1, obstacle.y0, obstacle.y1)
        if vertical_overlap <= 0.5:
            continue
        if obstacle.x1 <= source_rect.x0:
            left = max(left, obstacle.x1 + gap)
        elif obstacle.x0 >= source_rect.x1:
            right = min(right, obstacle.x0 - gap)

    if right - left < base_rect.width + 12:
        return candidates

    max_height = max(base_rect.height, source_rect.height + (block.style.font_size * 3.2))
    bottom = min(page.rect.y1 - margin, source_rect.y0 + max_height)
    expanded = fitz.Rect(left, base_rect.y0, right, bottom)

    for obstacle in obstacle_rects:
        obstacle = fitz.Rect(obstacle)
        if _same_rect(source_rect, obstacle):
            continue
        horizontal_overlap = _overlap_amount(expanded.x0, expanded.x1, obstacle.x0, obstacle.x1)
        if horizontal_overlap <= 0:
            continue
        overlap_ratio = horizontal_overlap / max(1.0, min(expanded.width, obstacle.width))
        if overlap_ratio < 0.12:
            continue
        if obstacle.y0 >= source_rect.y1:
            expanded.y1 = min(expanded.y1, obstacle.y0 - gap)

    if expanded.width > base_rect.width + 12 and expanded.height >= base_rect.height:
        candidates.append(expanded)

    unique: list[fitz.Rect] = []
    for rect in candidates:
        if not any(_same_rect(rect, existing) for existing in unique):
            unique.append(rect)
    return unique


def _measure_textbox_spare(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    *,
    fontname: str,
    fontfile: str | None,
    fontsize: float,
    color: tuple[float, float, float],
    lineheight: float,
) -> float:
    scratch = fitz.open()
    try:
        scratch_page = scratch.new_page(width=page.rect.width, height=page.rect.height)
        if fontfile:
            scratch_page.insert_font(fontname=fontname, fontfile=fontfile)
        return scratch_page.insert_textbox(
            rect,
            text,
            fontname=fontname,
            fontfile=fontfile,
            fontsize=fontsize,
            color=color,
            align=fitz.TEXT_ALIGN_LEFT,
            lineheight=lineheight,
            overlay=True,
        )
    finally:
        scratch.close()


@dataclass(frozen=True)
class _BlockWritePlan:
    """A fully-resolved placement for one block, ready to be written to the page.

    Planning is deliberately side-effect free: it decides *where* and *how* the
    translation will be drawn but touches neither the source glyphs nor the page.
    The caller applies every block's redaction first and only then inserts text,
    so a later block's redaction can never erase text already placed for an
    earlier, spatially overlapping block.
    """

    redaction_rect: fitz.Rect
    placed_rect: fitz.Rect
    render_text: str
    fontname: str
    fontfile: str | None
    fontsize: float
    line_height: float
    color: tuple[float, float, float]


def _plan_block_write(
    page: fitz.Page,
    block: ExtractedTextBlock,
    translated: str,
    protected_rects: list[fitz.Rect] | None = None,
    obstacle_rects: list[fitz.Rect] | None = None,
) -> tuple[str, _BlockWritePlan | None]:
    """Decide how ``translated`` should be rendered into ``block``'s box.

    Pure (no page mutation). Returns ``(status, plan)`` where status is one of:
    ``"fit"`` (a placement was found; ``plan`` is non-None), ``"unplaced"``
    (translation could not be placed at a readable size, so source text should be
    preserved), or ``"skipped"`` (degenerate/empty box, source left untouched).
    """
    source_rect = fitz.Rect(*block.bbox)
    rect = fitz.Rect(source_rect)
    if rect.width < 3 or rect.height < 3:
        return "skipped", None

    text = re.sub(r"\s*\n+\s*", " ", translated).strip()
    if not text:
        return "skipped", None

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

    # Clamp the box bottom so a reflowed translation (typically longer than the
    # source) cannot spill into the block directly below it in the same column.
    # Without this, merged multi-line paragraphs keep their font size and grow
    # downward, overlapping the next paragraph. The font-shrink search below
    # then fits the text into whatever vertical room is actually available.
    #
    # A neighbour counts as "below" when it *starts* clearly lower than this
    # block's top — not when it starts below this block's bottom. On these
    # tightly-packed posters, adjacent source line/paragraph boxes overlap by a
    # few points, so keying off the bottom edge made the clamp never fire.
    if not display_block and obstacle_rects:
        vertical_limit = page.rect.y1 - 2.0
        start_threshold = source_rect.y0 + max(4.0, block.style.font_size * 0.6)
        for obstacle in obstacle_rects:
            obstacle = fitz.Rect(obstacle)
            if _same_rect(source_rect, obstacle):
                continue
            if obstacle.y0 <= start_threshold:
                continue  # same row or above — not a block below this one
            horizontal_overlap = _overlap_amount(
                source_rect.x0, source_rect.x1, obstacle.x0, obstacle.x1
            )
            if horizontal_overlap <= min(source_rect.width, obstacle.width) * 0.30:
                continue  # different column / no real collision
            vertical_limit = min(vertical_limit, obstacle.y0 - 1.0)
        # Prefer never overlapping the block below; keep at least ~one line so a
        # degenerate slot falls through to the fit search (which may shrink or
        # leave the block unplaced) rather than producing a zero-height box.
        rect.y1 = max(source_rect.y0 + 10.0, min(rect.y1, vertical_limit))

    candidate_rects = _candidate_layout_rects(
        page,
        block,
        source_rect,
        rect,
        obstacle_rects or [],
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

    minimum_size = min(size, 7.0)
    placed_size: float | None = None
    placed_line_height = line_height
    placed_rect = rect
    line_height_candidates = (
        line_height,
        min(line_height, 1.0),
        min(line_height, 0.94),
    )
    for candidate_rect in candidate_rects:
        for candidate_line_height in line_height_candidates:
            candidate_size = size
            while candidate_size >= minimum_size - 0.01:
                spare = _measure_textbox_spare(
                    page,
                    candidate_rect,
                    render_text,
                    fontname=fontname,
                    fontfile=fontfile,
                    fontsize=candidate_size,
                    color=block.style.color_rgb,
                    lineheight=candidate_line_height,
                )
                # Require a genuine fit (non-negative spare). ``insert_textbox``
                # renders NOTHING when the text overflows even slightly, so a
                # lenient threshold here would "place" text that then silently
                # vanishes at write time — accept only sizes that truly fit.
                if spare >= 0.0:
                    placed_size = candidate_size
                    placed_line_height = candidate_line_height
                    placed_rect = candidate_rect
                    break
                candidate_size *= 0.92
            if placed_size is not None:
                break
        if placed_size is not None:
            break

    snippet = text[:60] + ("…" if len(text) > 60 else "")
    if placed_size is None:
        print(
            f"⚠️  block {block.block_id} ({block.kind}) p{block.page_index + 1}: "
            f"translation could not fit at readable size — UNPLACED, source kept: {snippet!r}"
        )
        return "unplaced", None

    # Resolve the redaction rectangle now, but do NOT mutate the page here.
    # Some extracted line boxes overlap vertically; keep protected-only contact
    # details out of the redaction rectangle so they remain exact.
    redaction_rect = _redaction_rect_avoiding(source_rect, protected_rects or [])
    if redaction_rect.width < 1.0 or redaction_rect.height < 1.0:
        return "unplaced", None
    plan = _BlockWritePlan(
        redaction_rect=redaction_rect,
        placed_rect=placed_rect,
        render_text=render_text,
        fontname=fontname,
        fontfile=fontfile,
        fontsize=placed_size,
        line_height=placed_line_height,
        color=block.style.color_rgb,
    )
    return "fit", plan


def _apply_block_plan(page: fitz.Page, plan: _BlockWritePlan) -> None:
    """Redact the source region for a single planned block and draw its text."""
    page.add_redact_annot(plan.redaction_rect, fill=None)
    page.apply_redactions(
        images=getattr(fitz, "PDF_REDACT_IMAGE_NONE", 0),
        graphics=getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0),
        text=getattr(fitz, "PDF_REDACT_TEXT_REMOVE", 0),
    )
    page.insert_textbox(
        plan.placed_rect,
        plan.render_text,
        fontname=plan.fontname,
        fontfile=plan.fontfile,
        fontsize=plan.fontsize,
        color=plan.color,
        align=fitz.TEXT_ALIGN_LEFT,
        lineheight=plan.line_height,
        overlay=True,
    )


def _fit_and_write_block(
    page: fitz.Page,
    block: ExtractedTextBlock,
    translated: str,
    protected_rects: list[fitz.Rect] | None = None,
    obstacle_rects: list[fitz.Rect] | None = None,
) -> str:
    """Plan and write one block in isolation (redact + insert immediately).

    Kept for single-block callers/tests. The batch path in
    :func:`translate_pdf_direct` must instead plan every block first, apply all
    redactions per page, and only then insert text — otherwise a later block's
    redaction erases text already placed for an earlier overlapping block.
    """
    status, plan = _plan_block_write(
        page,
        block,
        translated,
        protected_rects=protected_rects,
        obstacle_rects=obstacle_rects,
    )
    if status != "fit" or plan is None:
        return status
    _apply_block_plan(page, plan)
    return "fit"


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

    protected_sources = {
        block.block_id: protect_nontranslatable_text(block.text) for block in blocks
    }
    protected_rects_by_page: dict[int, list[fitz.Rect]] = {}
    obstacle_rects_by_page: dict[int, list[fitz.Rect]] = {}
    for block in blocks:
        block_rect = fitz.Rect(*block.bbox)
        obstacle_rects_by_page.setdefault(block.page_index, []).append(block_rect)
        protected_source = protected_sources[block.block_id]
        if has_unprotected_translatable_text(protected_source.text):
            continue
        protected_rects_by_page.setdefault(block.page_index, []).append(block_rect)

    translated_map: Dict[int, str] = {}
    api_calls = 0
    retried = 0
    rejected = 0

    for i, block in enumerate(blocks, start=1):
        if i % 25 == 0 or i == len(blocks):
            print(f"Translating lines: {i}/{len(blocks)}")
        protected_source = protected_sources[block.block_id]
        if not has_unprotected_translatable_text(protected_source.text):
            continue
        if is_contact_identity_text(protected_source.text):
            continue
        candidate_raw = translator.translate_single_strict(
            protected_source.text,
            source_lang,
            target_lang,
        )
        api_calls += 1
        if not candidate_raw:
            rejected += 1
            continue
        candidate_for_retry = re.sub(r"\s*\n+\s*", " ", candidate_raw).strip()
        candidate = restore_protected_text(
            candidate_for_retry,
            protected_source.replacements,
        ).strip()

        needs_retry = len(block.text.strip()) > 16 and should_retry_translation(
            protected_source.text, candidate_for_retry, source_lang, target_lang
        )
        if contains_protected_token(candidate):
            needs_retry = True

        if needs_retry:
            retry_raw = translator.translate_single_strict(
                protected_source.text,
                source_lang,
                target_lang,
            )
            api_calls += 1
            retried += 1
            if not retry_raw:
                rejected += 1
                continue
            retry_for_retry = re.sub(r"\s*\n+\s*", " ", retry_raw).strip()
            retry = restore_protected_text(
                retry_for_retry,
                protected_source.replacements,
            ).strip()
            if should_retry_translation(
                protected_source.text, retry_for_retry, source_lang, target_lang
            ) or contains_protected_token(retry):
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
        unplaced_count = 0
        # Phase 1: plan every block's placement without touching the page, and
        # queue redaction annotations. Text is inserted only in phase 2, after
        # all redactions for a page have been applied — otherwise a later block's
        # redaction would erase text already placed for an earlier overlapping
        # block (adjacent line boxes overlap), silently blanking the output.
        plans_by_page: dict[int, list[_BlockWritePlan]] = {}
        for block in blocks:
            translated = translated_map.get(block.block_id)
            if not translated:
                continue
            page = doc[block.page_index]
            status, plan = _plan_block_write(
                page,
                block,
                translated,
                protected_rects=protected_rects_by_page.get(block.page_index),
                obstacle_rects=obstacle_rects_by_page.get(block.page_index),
            )
            if status == "fit" and plan is not None:
                translated_count += 1
                plans_by_page.setdefault(block.page_index, []).append(plan)
                page.add_redact_annot(plan.redaction_rect, fill=None)
            elif status == "unplaced":
                unplaced_count += 1

        # Phase 2: apply all redactions for a page in one pass, then draw text.
        for page_index, page in enumerate(doc):
            page_plans = plans_by_page.get(page_index)
            if not page_plans:
                continue
            page.apply_redactions(
                images=getattr(fitz, "PDF_REDACT_IMAGE_NONE", 0),
                graphics=getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0),
                text=getattr(fitz, "PDF_REDACT_TEXT_REMOVE", 0),
            )
            for plan in page_plans:
                page.insert_textbox(
                    plan.placed_rect,
                    plan.render_text,
                    fontname=plan.fontname,
                    fontfile=plan.fontfile,
                    fontsize=plan.fontsize,
                    color=plan.color,
                    align=fitz.TEXT_ALIGN_LEFT,
                    lineheight=plan.line_height,
                    overlay=True,
                )
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
    if truncated_count or unplaced_count:
        print(
            f"⚠️  Layout fit: {truncated_count} block(s) truncated, "
            f"{unplaced_count} block(s) unplaced with source preserved."
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
        blocks_unplaced=unplaced_count,
        blocks_dropped=0,
        image_regions_processed=image_stats.image_regions_processed if image_stats else 0,
        image_blocks_translated=image_stats.image_blocks_translated if image_stats else 0,
        image_blocks_rejected=image_stats.image_blocks_rejected if image_stats else 0,
        image_api_calls=image_stats.api_calls if image_stats else 0,
    )
