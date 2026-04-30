from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

import fitz

from app.pipeline.fonts import sanitize_text_for_rendering
from app.pipeline.translate_pdf_direct import _capture_page_links, _restore_page_links
from app.pipeline.translator_llm import _normalize_detected_language_code, _prepare_language_detection_samples


class DirectPipelineHelperTests(unittest.TestCase):
    def test_prepare_language_detection_samples_filters_noisy_rows(self) -> None:
        prepared = _prepare_language_detection_samples(
            [
                "Page 3",
                "https://example.com/resource",
                "0.001 mg kg−1   98   12",
                "The intervention was evaluated over twelve months in commercial poultry systems.",
                "Results indicate the method remained stable across all partner sites and seasons.",
            ]
        )

        self.assertGreaterEqual(len(prepared), 1)
        self.assertIn("intervention was evaluated", prepared[0])
        self.assertNotIn("https://example.com", " ".join(prepared))

    def test_detected_language_code_normalizes_supported_values(self) -> None:
        self.assertEqual(_normalize_detected_language_code("EN-us"), "en")
        self.assertEqual(_normalize_detected_language_code("el-GR"), "el")
        self.assertIsNone(_normalize_detected_language_code("xx"))

    def test_sanitize_text_for_rendering_rewrites_fragile_symbols(self) -> None:
        self.assertEqual(
            sanitize_text_for_rendering("“Quoted” ❑"),
            "\"Quoted\" □",
        )

    def test_capture_and_restore_page_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "link-test.pdf"
            doc = fitz.open()
            try:
                page = doc.new_page()
                page.insert_text((72, 72), "Example")
                _restore_page_links(
                    page,
                    [
                        {
                            "kind": fitz.LINK_URI,
                            "from": fitz.Rect(72, 60, 120, 80),
                            "uri": "https://example.com",
                        }
                    ],
                )
                doc.save(pdf_path)
            finally:
                doc.close()

            reopened = fitz.open(pdf_path)
            try:
                page = reopened[0]
                restored = page.get_links()
                self.assertEqual(len(restored), 1)
                self.assertEqual(restored[0].get("uri"), "https://example.com")
                self.assertEqual(len(_capture_page_links(page)), 1)
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
