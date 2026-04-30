from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup, Tag

from app.pipeline.translator_llm import LLMTranslator, should_retry_translation
from app.pipeline.vision_llm import VisionLLMClient, VisionTextBlock


def _extract_page_dimensions(page_div: Tag) -> tuple[float, float]:
    style = page_div.get("style", "")
    width_match = re.search(r"width:\s*([0-9.]+)px", style)
    height_match = re.search(r"height:\s*([0-9.]+)px", style)
    width = float(width_match.group(1)) if width_match else 0.0
    height = float(height_match.group(1)) if height_match else 0.0
    return (width, height)


def _normalized_to_page_bbox(
    block: VisionTextBlock,
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = block.bbox_norm
    return (
        page_width * x1 / 1000.0,
        page_height * y1 / 1000.0,
        page_width * x2 / 1000.0,
        page_height * y2 / 1000.0,
    )


def _translated_block_text(
    translator: LLMTranslator,
    source_text: str,
    source_lang: str,
    target_lang: str,
) -> Optional[str]:
    candidate = translator.translate_single_strict(source_text, source_lang, target_lang)
    if not candidate:
        return None
    candidate = re.sub(r"\s*\n+\s*", " ", candidate).strip()

    if should_retry_translation(source_text, candidate, source_lang, target_lang):
        retry = translator.translate_single_strict(source_text, source_lang, target_lang)
        if not retry:
            return None
        retry = re.sub(r"\s*\n+\s*", " ", retry).strip()
        if should_retry_translation(source_text, retry, source_lang, target_lang):
            return None
        candidate = retry

    return candidate


def _append_overlay(page_div: Tag, bbox: tuple[float, float, float, float], translated_text: str) -> None:
    x1, y1, x2, y2 = bbox
    width = max(36.0, (x2 - x1) * 1.18)
    height = max(18.0, (y2 - y1) * 1.35)
    font_size = max(10.0, min(24.0, (y2 - y1) * 0.72))
    left = max(0.0, x1 - 2.0)
    top = max(0.0, y1 - 2.0)
    escaped_text = html.escape(translated_text)

    overlay_html = (
        f'<div class="vision-overlay" style="position:absolute; left:{left:.1f}px; top:{top:.1f}px; '
        f'width:{width:.1f}px; min-height:{height:.1f}px; padding:2px 4px; '
        "box-sizing:border-box; background:rgba(255,255,255,0.92); color:#111; "
        f'font-size:{font_size:.1f}px; line-height:1.15; font-family:Arial,sans-serif; '
        "white-space:normal; overflow-wrap:anywhere; border-radius:2px; z-index:12; "
        f'">{escaped_text}</div>'
    )
    overlay_node = BeautifulSoup(overlay_html, "lxml").body.div
    if overlay_node is not None:
        page_div.append(overlay_node)


def translate_html_image_text(
    html_path: Path,
    *,
    target_lang: str,
    source_lang: str,
) -> int:
    if source_lang == target_lang:
        return 0

    soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="ignore"), "lxml")
    vision = VisionLLMClient()
    translator = LLMTranslator()
    html_dir = html_path.parent
    translated_blocks = 0

    for page_div in soup.find_all("div", id=re.compile(r"^page\d+-div$")):
        page_width, page_height = _extract_page_dimensions(page_div)
        if page_width <= 0 or page_height <= 0:
            continue

        background_img = page_div.find("img", attrs={"alt": "background image"})
        if background_img is None:
            continue

        src = background_img.get("src")
        if not src:
            continue

        image_path = (html_dir / src).resolve()
        if not image_path.exists():
            continue

        blocks = vision.extract_figure_text_blocks(image_path)
        if not blocks:
            continue

        for block in blocks:
            translated = _translated_block_text(
                translator,
                block.text,
                source_lang,
                target_lang,
            )
            if not translated:
                continue
            bbox = _normalized_to_page_bbox(block, page_width, page_height)
            _append_overlay(page_div, bbox, translated)
            translated_blocks += 1

    if translated_blocks:
        html_path.write_text(str(soup), encoding="utf-8")

    return translated_blocks
