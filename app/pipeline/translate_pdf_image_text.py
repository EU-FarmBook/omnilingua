from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import fitz  # PyMuPDF

from app.pipeline.block_schema import TextStyleHint
from app.pipeline.fonts import resolve_font_for_text
from app.pipeline.translator_factory import get_translator
from app.pipeline.translator_llm import should_retry_translation
from app.pipeline.vision_llm import VisionLLMClient, VisionTextBlock


@dataclass(frozen=True)
class ImageTextTranslationStats:
    image_regions_processed: int
    image_blocks_translated: int
    image_blocks_rejected: int
    api_calls: int


def _iter_image_rects(page: fitz.Page) -> Iterable[fitz.Rect]:
    seen: set[tuple[float, float, float, float]] = set()
    for image_info in page.get_images(full=True):
        xref = image_info[0]
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            continue
        for rect in rects:
            key = (round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2))
            if key in seen:
                continue
            seen.add(key)
            yield rect


def _is_useful_image_rect(rect: fitz.Rect) -> bool:
    return rect.width >= 80 and rect.height >= 50


def _normalized_block_to_pdf_rect(block: VisionTextBlock, image_rect: fitz.Rect) -> fitz.Rect:
    x1, y1, x2, y2 = block.bbox_norm
    return fitz.Rect(
        image_rect.x0 + (x1 / 1000.0) * image_rect.width,
        image_rect.y0 + (y1 / 1000.0) * image_rect.height,
        image_rect.x0 + (x2 / 1000.0) * image_rect.width,
        image_rect.y0 + (y2 / 1000.0) * image_rect.height,
    )


def _translate_block_text(
    translator,
    source_text: str,
    source_lang: str,
    target_lang: str,
) -> tuple[Optional[str], int]:
    api_calls = 0
    candidate = translator.translate_single_strict(source_text, source_lang, target_lang)
    api_calls += 1
    if not candidate:
        return (None, api_calls)
    candidate = re.sub(r"\s*\n+\s*", " ", candidate).strip()

    if should_retry_translation(source_text, candidate, source_lang, target_lang):
        retry = translator.translate_single_strict(source_text, source_lang, target_lang)
        api_calls += 1
        if not retry:
            return (None, api_calls)
        retry = re.sub(r"\s*\n+\s*", " ", retry).strip()
        if should_retry_translation(source_text, retry, source_lang, target_lang):
            return (None, api_calls)
        candidate = retry

    return (candidate, api_calls)


def _measure_overlay_spare(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    *,
    font_name: str,
    font_file: Optional[str],
    font_size: float,
) -> float:
    """Return insert_textbox's spare for ``text`` at ``font_size`` without drawing."""
    scratch = fitz.open()
    try:
        scratch_page = scratch.new_page(width=page.rect.width, height=page.rect.height)
        if font_file:
            scratch_page.insert_font(fontname=font_name, fontfile=font_file)
        return scratch_page.insert_textbox(
            rect,
            text,
            fontname=font_name,
            fontfile=font_file,
            fontsize=font_size,
            align=fitz.TEXT_ALIGN_LEFT,
            lineheight=1.08,
            overlay=True,
        )
    finally:
        scratch.close()


def _overlay_text_on_rect(page: fitz.Page, rect: fitz.Rect, translated_text: str) -> bool:
    target_rect = fitz.Rect(rect.x0 - 1.5, rect.y0 - 1.5, rect.x1 + 1.5, rect.y1 + 1.5)
    if target_rect.width < 12 or target_rect.height < 8:
        target_rect = fitz.Rect(target_rect.x0, target_rect.y0, target_rect.x0 + max(24, target_rect.width), target_rect.y0 + max(12, target_rect.height))

    style = TextStyleHint(
        font_name="Arial",
        font_size=max(7.5, min(18.0, target_rect.height * 0.72)),
        color_rgb=(0.05, 0.05, 0.05),
    )
    font_name, font_file, render_text = resolve_font_for_text(page, style, translated_text)

    # Find a size that genuinely fits BEFORE painting anything. insert_textbox
    # renders *nothing* when the text overflows even slightly (so the old
    # ``spare >= -0.5`` accepted sizes that drew no glyphs), and the white cover
    # rectangle used to be painted first — together that stamped a blank white
    # box over the original figure text whenever the translation would not fit
    # ("white boxes on the title", unreadable legends). Measure on a scratch page
    # and only cover + draw when a real fit exists; otherwise leave the original
    # image text in place (untranslated is better than a blank box).
    font_size = style.font_size
    minimum_size = 6.0
    placed_size: float | None = None
    while font_size >= minimum_size - 0.01:
        spare = _measure_overlay_spare(
            page,
            target_rect,
            render_text,
            font_name=font_name,
            font_file=font_file,
            font_size=font_size,
        )
        if spare >= 0.0:
            placed_size = font_size
            break
        font_size *= 0.92

    if placed_size is None:
        return False

    page.draw_rect(target_rect, color=None, fill=(1, 1, 1), overlay=True)
    page.insert_textbox(
        target_rect,
        render_text,
        fontname=font_name,
        fontfile=font_file,
        fontsize=placed_size,
        color=style.color_rgb,
        align=fitz.TEXT_ALIGN_LEFT,
        lineheight=1.08,
        overlay=True,
    )
    return True


def translate_pdf_image_text(
    doc: fitz.Document,
    *,
    source_lang: str,
    target_lang: str,
    engine: Optional[str] = None,
) -> ImageTextTranslationStats:
    if source_lang == target_lang:
        return ImageTextTranslationStats(0, 0, 0, 0)

    vision = VisionLLMClient()
    translator = get_translator(engine)
    image_regions_processed = 0
    image_blocks_translated = 0
    image_blocks_rejected = 0
    api_calls = 0

    with tempfile.TemporaryDirectory(prefix="omnilingua_image_text_") as tmpdir:
        temp_root = Path(tmpdir)
        for page_index, page in enumerate(doc):
            for image_idx, rect in enumerate(_iter_image_rects(page), start=1):
                if not _is_useful_image_rect(rect):
                    continue

                image_regions_processed += 1
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=rect, alpha=False)
                image_path = temp_root / f"page_{page_index + 1}_image_{image_idx}.png"
                pixmap.save(image_path)

                blocks = vision.extract_figure_text_blocks(image_path)
                if not blocks:
                    continue

                for block in blocks[:20]:
                    translated, translation_calls = _translate_block_text(
                        translator,
                        block.text,
                        source_lang,
                        target_lang,
                    )
                    api_calls += translation_calls
                    if not translated:
                        image_blocks_rejected += 1
                        continue

                    pdf_rect = _normalized_block_to_pdf_rect(block, rect)
                    if _overlay_text_on_rect(page, pdf_rect, translated):
                        image_blocks_translated += 1
                    else:
                        image_blocks_rejected += 1

    return ImageTextTranslationStats(
        image_regions_processed=image_regions_processed,
        image_blocks_translated=image_blocks_translated,
        image_blocks_rejected=image_blocks_rejected,
        api_calls=api_calls,
    )
