from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.pipeline.translate_html_image_text import translate_html_image_text
from app.pipeline.vision_llm import VisionTextBlock


class TranslateHtmlImageTextTests(unittest.TestCase):
    def test_injects_overlay_for_translated_vision_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            html_path = tmp_path / "sample.html"
            image_path = tmp_path / "sample001.png"
            image_path.write_bytes(b"fake-image")
            html_path.write_text(
                """
                <html><body>
                <div id="page1-div" style="position:relative;width:1000px;height:800px;">
                  <img width="1000" height="800" src="sample001.png" alt="background image"/>
                </div>
                </body></html>
                """,
                encoding="utf-8",
            )

            with patch("app.pipeline.translate_html_image_text.VisionLLMClient") as vision_cls, patch(
                "app.pipeline.translate_html_image_text.get_translator"
            ) as get_translator:
                vision_cls.return_value.extract_figure_text_blocks.return_value = [
                    VisionTextBlock(text="Filter System 1", bbox_norm=(100, 200, 300, 260))
                ]
                translator = get_translator.return_value
                translator.translate_single_strict.return_value = "Σύστημα φίλτρου 1"

                translated = translate_html_image_text(
                    html_path,
                    target_lang="el",
                    source_lang="en",
                )

            self.assertEqual(translated, 1)
            html_output = html_path.read_text(encoding="utf-8")
            self.assertIn("vision-overlay", html_output)
            self.assertIn("Σύστημα φίλτρου 1", html_output)

    def test_returns_zero_when_source_and_target_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = Path(tmpdir) / "sample.html"
            html_path.write_text("<html><body></body></html>", encoding="utf-8")

            with patch("app.pipeline.translate_html_image_text.VisionLLMClient") as vision_cls, patch(
                "app.pipeline.translate_html_image_text.get_translator"
            ) as get_translator:
                translated = translate_html_image_text(
                    html_path,
                    target_lang="en",
                    source_lang="en",
                )

            self.assertEqual(translated, 0)
            vision_cls.assert_not_called()
            get_translator.assert_not_called()


if __name__ == "__main__":
    unittest.main()
