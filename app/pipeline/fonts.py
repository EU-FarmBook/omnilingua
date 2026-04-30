from __future__ import annotations

from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

from app.pipeline.block_schema import TextStyleHint


UNICODE_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansGreek-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansSymbols-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]

_WARNED_MISSING_UNICODE_FONT = False


def pick_base_font(font_name: str) -> str:
    name = font_name.lower()
    bold = "bold" in name or name.endswith("bd")
    italic = "italic" in name or "oblique" in name or name.endswith("it")
    if bold and italic:
        return "hebi"
    if bold:
        return "hebo"
    if italic:
        return "heit"
    return "helv"


def needs_unicode_font(text: str) -> bool:
    for ch in text:
        cp = ord(ch)
        if cp > 0x024F:
            return True
        if ch in {"“", "”", "„", "‟", "’", "‘", "↑", "↓", "←", "→", "↔", "•", "▪", "❑", "✓", "✔"}:
            return True
    return False


def resolve_unicode_font_file() -> Optional[str]:
    for path in UNICODE_FONT_CANDIDATES:
        if Path(path).exists():
            return path
    return None


def resolve_font_for_text(page: fitz.Page, style: TextStyleHint, text: str) -> tuple[str, Optional[str]]:
    font_name = pick_base_font(style.font_name)
    font_file = None

    if not needs_unicode_font(text):
        return (font_name, font_file)

    global _WARNED_MISSING_UNICODE_FONT
    font_file = resolve_unicode_font_file()
    if font_file:
        font_name = "unicode_fallback"
        page.insert_font(fontname=font_name, fontfile=font_file)
        return (font_name, font_file)

    if not _WARNED_MISSING_UNICODE_FONT:
        print("Warning: No Unicode font found. Non-Latin scripts and symbols may render incorrectly.")
        _WARNED_MISSING_UNICODE_FONT = True
    return (font_name, font_file)
