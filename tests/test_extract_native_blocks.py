from __future__ import annotations

import unittest

from app.pipeline.block_schema import ExtractedTextBlock, TextStyleHint
from app.pipeline.extract_native_blocks import (
    _can_merge_lines,
    _classify_scholarly_kind,
    _detect_multicolumn_page,
    collect_language_detection_samples,
    _sort_page_lines,
    _with_column_metadata,
)


def _block(block_id: int, x0: float, y0: float, x1: float, y1: float, text: str) -> ExtractedTextBlock:
    return ExtractedTextBlock(
        block_id=block_id,
        page_index=0,
        bbox=(x0, y0, x1, y1),
        text=text,
        source="native",
        kind="line",
        confidence=1.0,
        style=TextStyleHint(font_name="Times", font_size=10.0, color_rgb=(0, 0, 0)),
        raw_block_id=block_id,
    )


class ExtractNativeBlocksTests(unittest.TestCase):
    def test_classifies_obvious_scholarly_blocks(self) -> None:
        self.assertEqual(
            _classify_scholarly_kind(
                "Miniaturized multiresidue method for determination",
                2,
                page_top=60,
                font_size=18,
                page_width=550,
                block_width=320,
            ),
            "title",
        )
        self.assertEqual(
            _classify_scholarly_kind(
                "Abstract Current work presents developed and validated method",
                2,
                page_top=120,
                font_size=10,
                page_width=550,
                block_width=220,
            ),
            "abstract",
        )
        self.assertEqual(
            _classify_scholarly_kind(
                "Figure 1. Recovery of analytes in beebread samples",
                1,
                page_top=500,
                font_size=9,
                page_width=550,
                block_width=250,
            ),
            "caption",
        )
        self.assertEqual(
            _classify_scholarly_kind(
                "0.001 mg kg−1   98   12",
                1,
                page_top=300,
                font_size=9,
                page_width=550,
                block_width=180,
            ),
            "table",
        )

    def test_detects_multicolumn_page(self) -> None:
        blocks = []
        for idx in range(8):
            blocks.append(_block(idx, 40, 100 + idx * 20, 210, 112 + idx * 20, f"L{idx}"))
        for idx in range(8, 16):
            blocks.append(_block(idx, 320, 100 + (idx - 8) * 20, 490, 112 + (idx - 8) * 20, f"R{idx}"))

        self.assertTrue(_detect_multicolumn_page(blocks, 550.0))

    def test_sorts_multicolumn_page_left_then_right_after_full_width_top(self) -> None:
        page_width = 550.0
        blocks = [
            _block(0, 40, 20, 500, 40, "Title"),
            _block(1, 40, 100, 210, 112, "L1"),
            _block(2, 320, 100, 490, 112, "R1"),
            _block(3, 40, 130, 210, 142, "L2"),
            _block(4, 320, 130, 490, 142, "R2"),
            _block(5, 40, 160, 210, 172, "L3"),
            _block(6, 320, 160, 490, 172, "R3"),
            _block(7, 40, 190, 210, 202, "L4"),
            _block(8, 320, 190, 490, 202, "R4"),
            _block(9, 40, 220, 210, 232, "L5"),
            _block(10, 320, 220, 490, 232, "R5"),
            _block(11, 40, 250, 210, 262, "L6"),
            _block(12, 320, 250, 490, 262, "R6"),
            _block(13, 40, 280, 210, 292, "L7"),
            _block(14, 320, 280, 490, 292, "R7"),
            _block(15, 40, 310, 210, 322, "L8"),
            _block(16, 320, 310, 490, 322, "R8"),
        ]

        with_columns = _with_column_metadata(blocks, page_width, multi_column=True)
        ordered = _sort_page_lines(with_columns, page_width, multi_column=True)

        ordered_text = [block.text for block in ordered]
        self.assertEqual(ordered_text[0], "Title")
        self.assertEqual(ordered_text[1:9], ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8"])
        self.assertEqual(ordered_text[9:], ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"])

    def test_detection_samples_skip_noisy_reference_and_table_content(self) -> None:
        style = TextStyleHint(font_name="Times", font_size=10.0, color_rgb=(0, 0, 0))
        blocks = [
            ExtractedTextBlock(
                block_id=1,
                page_index=0,
                bbox=(0, 0, 100, 20),
                text="Abstract This study investigates how farm health interventions scale across regions.",
                source="native",
                kind="abstract",
                confidence=1.0,
                style=style,
            ),
            ExtractedTextBlock(
                block_id=2,
                page_index=0,
                bbox=(0, 30, 100, 50),
                text="[1] Smith et al. (2023) https://doi.org/example",
                source="native",
                kind="reference",
                confidence=1.0,
                style=style,
            ),
            ExtractedTextBlock(
                block_id=3,
                page_index=0,
                bbox=(0, 60, 100, 80),
                text="0.001 mg kg−1   98   12",
                source="native",
                kind="table",
                confidence=1.0,
                style=style,
            ),
            ExtractedTextBlock(
                block_id=4,
                page_index=0,
                bbox=(0, 90, 100, 110),
                text="The protocol was evaluated under realistic farm conditions across multiple partner sites.",
                source="native",
                kind="paragraph",
                confidence=1.0,
                style=style,
            ),
        ]

        samples = collect_language_detection_samples(blocks)

        self.assertEqual(len(samples), 1)
        self.assertIn("realistic farm conditions", samples[0])

    def test_does_not_merge_reference_like_lines(self) -> None:
        left = _block(1, 40, 100, 260, 112, "[1] Smith et al. (2023) Journal of Tests")
        right = _block(2, 40, 114, 260, 126, "https://doi.org/10.1000/test")
        self.assertFalse(_can_merge_lines(left, right, multi_column=False))


if __name__ == "__main__":
    unittest.main()
