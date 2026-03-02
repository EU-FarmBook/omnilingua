from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF

from app.pipeline.translator_llm import LLMTranslator, should_retry_translation


@dataclass
class PDFTextLine:
    line_id: int
    page_index: int
    bbox: Tuple[float, float, float, float]
    text: str
    font_name: str
    font_size: float
    color_rgb: Tuple[float, float, float]


@dataclass(frozen=True)
class DirectTranslationStats:
    blocks_total: int
    blocks_translated: int
    blocks_skipped: int
    blocks_retried: int
    blocks_rejected: int
    api_calls: int
    source_lang: str


_UNICODE_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansGreek-Regular.ttf",
]
_WARNED_MISSING_UNICODE_FONT = False


def _is_translatable_text(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 2:
        return False
    letters = sum(1 for c in stripped if c.isalpha())
    if letters < 2:
        return False
    digits = sum(1 for c in stripped if c.isdigit())
    if digits > 0 and letters <= digits:
        return False
    return True


def _int_color_to_rgb(color: int) -> Tuple[float, float, float]:
    r = ((color >> 16) & 255) / 255.0
    g = ((color >> 8) & 255) / 255.0
    b = (color & 255) / 255.0
    return (r, g, b)


def _extract_lines(pdf_path: Path) -> List[PDFTextLine]:
    doc = fitz.open(str(pdf_path))
    lines_out: List[PDFTextLine] = []
    line_id = 0
    try:
        for page_index, page in enumerate(doc):
            text_dict = page.get_text("dict")
            for block in text_dict.get("blocks", []):
                if block.get("type", 0) != 0:
                    continue
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    if not spans:
                        continue
                    text = "".join(str(s.get("text", "")) for s in spans).strip()
                    if not _is_translatable_text(text):
                        continue
                    bbox_raw = line.get("bbox")
                    if not bbox_raw or len(bbox_raw) != 4:
                        continue
                    first = spans[0]
                    font_name = str(first.get("font", "helv"))
                    size = float(first.get("size", 11.0))
                    color = int(first.get("color", 0))
                    bbox = tuple(float(v) for v in bbox_raw)
                    lines_out.append(
                        PDFTextLine(
                            line_id=line_id,
                            page_index=page_index,
                            bbox=(bbox[0], bbox[1], bbox[2], bbox[3]),
                            text=text,
                            font_name=font_name,
                            font_size=size if size > 0 else 11.0,
                            color_rgb=_int_color_to_rgb(color),
                        )
                    )
                    line_id += 1
        return lines_out
    finally:
        doc.close()


def _pick_font(font_name: str) -> str:
    n = font_name.lower()
    bold = "bold" in n or n.endswith("bd")
    italic = "italic" in n or "oblique" in n or n.endswith("it")
    if bold and italic:
        return "hebi"
    if bold:
        return "hebo"
    if italic:
        return "heit"
    return "helv"


def _needs_unicode_font(text: str) -> bool:
    # Greek + Coptic, Cyrillic, Arabic, Hebrew, CJK, etc.
    for ch in text:
        cp = ord(ch)
        if (
            0x0370 <= cp <= 0x03FF
            or 0x0400 <= cp <= 0x04FF
            or 0x0590 <= cp <= 0x05FF
            or 0x0600 <= cp <= 0x06FF
            or 0x4E00 <= cp <= 0x9FFF
            or 0x3040 <= cp <= 0x30FF
            or 0xAC00 <= cp <= 0xD7AF
        ):
            return True
    return False


def _resolve_unicode_font_file() -> Optional[str]:
    for p in _UNICODE_FONT_CANDIDATES:
        if Path(p).exists():
            return p
    return None


def _fit_and_write_line(page: fitz.Page, line: PDFTextLine, translated: str) -> bool:
    rect = fitz.Rect(*line.bbox)
    if rect.width < 3 or rect.height < 3:
        return False

    text = re.sub(r"\s*\n+\s*", " ", translated).strip()
    if not text:
        return False

    # Expand line box a bit to support longer translation.
    min_h = max(rect.height, line.font_size * 1.35)
    rect = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + min_h)

    # Remove source text in this line box while preserving images / line art / background.
    page.add_redact_annot(rect, fill=None)
    page.apply_redactions(
        images=getattr(fitz, "PDF_REDACT_IMAGE_NONE", 0),
        graphics=getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0),
        text=getattr(fitz, "PDF_REDACT_TEXT_REMOVE", 0),
    )

    fontname = _pick_font(line.font_name)
    fontfile = None
    if _needs_unicode_font(text):
        global _WARNED_MISSING_UNICODE_FONT
        fontfile = _resolve_unicode_font_file()
        if fontfile:
            # Register per-page font alias so insert_textbox can use it.
            fontname = "unicode_fallback"
            page.insert_font(fontname=fontname, fontfile=fontfile)
        elif not _WARNED_MISSING_UNICODE_FONT:
            print("Warning: No Unicode font found. Non-Latin scripts may render as '?'.")
            _WARNED_MISSING_UNICODE_FONT = True
    size = max(6.5, min(line.font_size, 28.0))

    for _ in range(10):
        spare = page.insert_textbox(
            rect,
            text,
            fontname=fontname,
            fontfile=fontfile,
            fontsize=size,
            color=line.color_rgb,
            align=fitz.TEXT_ALIGN_LEFT,
            lineheight=1.12,
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
        color=line.color_rgb,
        align=fitz.TEXT_ALIGN_LEFT,
        lineheight=1.1,
        overlay=True,
    )
    return spare >= -3.0


def translate_pdf_direct(
    pdf_in: Path,
    pdf_out: Path,
    target_lang: str,
    source_lang: Optional[str] = None,
) -> DirectTranslationStats:
    lines = _extract_lines(pdf_in)
    if not lines:
        raise RuntimeError("No translatable text lines found in PDF.")

    translator = LLMTranslator()
    if source_lang is None:
        samples = [item.text for item in lines if len(item.text) > 20][:25]
        source_lang = translator.detect_language(samples)
        print(f"Detected source language: {source_lang}")

    if source_lang == target_lang:
        raise ValueError(f"Source and target language are the same ({source_lang}).")

    translated_map: Dict[int, str] = {}
    api_calls = 0
    retried = 0
    rejected = 0

    for i, item in enumerate(lines, start=1):
        if i % 25 == 0 or i == len(lines):
            print(f"Translating lines: {i}/{len(lines)}")
        candidate = translator.translate_single_strict(item.text, source_lang, target_lang)
        api_calls += 1
        if not candidate:
            rejected += 1
            continue
        candidate = re.sub(r"\s*\n+\s*", " ", candidate).strip()

        if len(item.text.strip()) > 16 and should_retry_translation(
            item.text, candidate, source_lang, target_lang
        ):
            retry = translator.translate_single_strict(item.text, source_lang, target_lang)
            api_calls += 1
            retried += 1
            if not retry:
                rejected += 1
                continue
            retry = re.sub(r"\s*\n+\s*", " ", retry).strip()
            if should_retry_translation(item.text, retry, source_lang, target_lang):
                rejected += 1
                continue
            candidate = retry

        translated_map[item.line_id] = candidate

    doc = fitz.open(str(pdf_in))
    try:
        translated_count = 0
        for item in lines:
            translated = translated_map.get(item.line_id)
            if not translated:
                continue
            page = doc[item.page_index]
            if _fit_and_write_line(page, item, translated):
                translated_count += 1
        pdf_out.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(pdf_out), garbage=3, deflate=True)
    finally:
        doc.close()

    print(f"Retried suspicious lines: {retried} (rejected: {rejected})")
    total = len(lines)
    return DirectTranslationStats(
        blocks_total=total,
        blocks_translated=translated_count,
        blocks_skipped=total - translated_count,
        blocks_retried=retried,
        blocks_rejected=rejected,
        api_calls=api_calls,
        source_lang=source_lang,
    )
