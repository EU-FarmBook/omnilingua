# pdf_page_size.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF


@dataclass(frozen=True)
class PageSize:
    """
    PDF page size in points (pt). 1 inch = 72 pt.
    Chromium expects strings like "595.28pt".
    """
    width_pt: float
    height_pt: float


def get_first_page_size(pdf_path: Path) -> PageSize:
    """
    Read the first page MediaBox size from a PDF.
    """
    doc = fitz.open(str(pdf_path))
    try:
        page = doc.load_page(0)
        rect = page.rect  # in points
        return PageSize(width_pt=float(rect.width), height_pt=float(rect.height))
    finally:
        doc.close()
