from __future__ import annotations

import unittest

import fitz

from app.pipeline.translate_pdf_image_text import (
    _is_useful_image_rect,
    _normalized_block_to_pdf_rect,
)
from app.pipeline.vision_llm import VisionTextBlock


class TranslatePdfImageTextTests(unittest.TestCase):
    def test_normalized_block_to_pdf_rect_maps_into_image_rect(self) -> None:
        image_rect = fitz.Rect(100, 200, 300, 500)
        block = VisionTextBlock(text="Label", bbox_norm=(100, 250, 600, 750))

        mapped = _normalized_block_to_pdf_rect(block, image_rect)

        self.assertAlmostEqual(mapped.x0, 120.0)
        self.assertAlmostEqual(mapped.y0, 275.0)
        self.assertAlmostEqual(mapped.x1, 220.0)
        self.assertAlmostEqual(mapped.y1, 425.0)

    def test_is_useful_image_rect_filters_tiny_regions(self) -> None:
        self.assertFalse(_is_useful_image_rect(fitz.Rect(0, 0, 40, 40)))
        self.assertFalse(_is_useful_image_rect(fitz.Rect(0, 0, 200, 40)))
        self.assertTrue(_is_useful_image_rect(fitz.Rect(0, 0, 120, 80)))


if __name__ == "__main__":
    unittest.main()
