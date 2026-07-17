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
TextAlignment = Literal["left", "center"]


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
    line_count: int = 1
    # How the source lines were aligned within the block box. Translations are
    # re-inserted with the same alignment so centered headings/captions do not
    # drift left when the translated text is shorter than the source.
    alignment: TextAlignment = "left"
    # Writing direction in degrees (0, 90, 180, 270), matching the ``rotate``
    # argument of ``insert_textbox``. 90 = reads bottom-to-top (dir (0,-1)),
    # 270 = top-to-bottom (dir (0,1)).
    rotation: int = 0
