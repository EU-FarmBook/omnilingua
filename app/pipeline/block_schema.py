from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Tuple


BBox = Tuple[float, float, float, float]
RGBColor = Tuple[float, float, float]
BlockSource = Literal["native", "vision"]
BlockKind = Literal[
    "line",
    "paragraph",
    "label",
    "bullet",
    "table",
    "title",
    "abstract",
    "keywords",
    "caption",
    "reference",
    "image_text",
    "unknown",
]


@dataclass(frozen=True)
class TextStyleHint:
    font_name: str
    font_size: float
    color_rgb: RGBColor


@dataclass(frozen=True)
class ExtractedTextBlock:
    block_id: int
    page_index: int
    bbox: BBox
    text: str
    source: BlockSource
    kind: BlockKind
    confidence: float
    style: TextStyleHint
    raw_block_id: int | None = None
    column_index: int | None = None
