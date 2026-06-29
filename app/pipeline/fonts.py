from __future__ import annotations

from pathlib import Path
from functools import lru_cache
from typing import Optional

import fitz  # PyMuPDF

from app.pipeline.block_schema import TextStyleHint


UNICODE_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansGreek-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansSymbols-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]

_WARNED_MISSING_UNICODE_FONT = False
_SYMBOL_FALLBACKS = {
    "“": "\"",
    "”": "\"",
    "„": "\"",
    "‟": "\"",
    "‘": "'",
    "’": "'",
    "↑": "↑",
    "↓": "↓",
    "←": "←",
    "→": "→",
    "↔": "↔",
    "❑": "□",
    "✓": "✔",
}


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
        # Base-14 Helvetica is limited to WinAnsi (Latin-1). Anything above U+00FF
        # — Latin Extended-A/B (Polish, Czech, Hungarian, Romanian, Baltic, Maltese,
        # …), Greek, Cyrillic — must use the Unicode fallback font or it renders as
        # notdef (".notdef" / "?") boxes.
        if cp > 0x00FF:
            return True
        if ch in {"“", "”", "„", "‟", "’", "‘", "↑", "↓", "←", "→", "↔", "•", "▪", "❑", "✓", "✔"}:
            return True
    return False


def sanitize_text_for_rendering(text: str) -> str:
    if not text:
        return text
    return "".join(_SYMBOL_FALLBACKS.get(ch, ch) for ch in text)


@lru_cache(maxsize=32)
def _load_font(font_path: str) -> Optional[fitz.Font]:
    try:
        return fitz.Font(fontfile=font_path)
    except Exception:
        return None


@lru_cache(maxsize=128)
def _font_supports_text(font_path: str, text: str) -> bool:
    font = _load_font(font_path)
    if font is None:
        return False
    for ch in text:
        if ch.isspace():
            continue
        try:
            if font.has_glyph(ord(ch)) <= 0:
                return False
        except Exception:
            return False
    return True


def resolve_unicode_font_file(text: str) -> Optional[str]:
    for path in UNICODE_FONT_CANDIDATES:
        if Path(path).exists() and _font_supports_text(path, text):
            return path
    for path in UNICODE_FONT_CANDIDATES:
        if Path(path).exists():
            return path
    return None


def resolve_font_for_text(page: fitz.Page, style: TextStyleHint, text: str) -> tuple[str, Optional[str], str]:
    sanitized = sanitize_text_for_rendering(text)
    font_name = pick_base_font(style.font_name)
    font_file = None

    if not needs_unicode_font(sanitized):
        return (font_name, font_file, sanitized)

    global _WARNED_MISSING_UNICODE_FONT
    font_file = resolve_unicode_font_file(sanitized)
    if font_file:
        font_name = "unicode_fallback"
        page.insert_font(fontname=font_name, fontfile=font_file)
        return (font_name, font_file, sanitized)

    if not _WARNED_MISSING_UNICODE_FONT:
        print("Warning: No Unicode font found. Non-Latin scripts and symbols may render incorrectly.")
        _WARNED_MISSING_UNICODE_FONT = True
    return (font_name, font_file, sanitized)
