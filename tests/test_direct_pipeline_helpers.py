from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import fitz

from app.pipeline.block_schema import ExtractedTextBlock, TextStyleHint
from app.pipeline.fonts import sanitize_text_for_rendering
from app.pipeline.protected_text import (
    has_unprotected_translatable_text,
    is_contact_identity_text,
    protect_nontranslatable_text,
    restore_protected_text,
)
from app.pipeline.translate_pdf_direct import (
    _capture_page_links,
    _fit_and_write_block,
    _restore_page_links,
    translate_pdf_direct,
)
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

    def test_protect_nontranslatable_text_round_trips_links_and_contacts(self) -> None:
        protected = protect_nontranslatable_text(
            "Contact rivera@agro-alimentarias.coop, visit https://example.org/page, or follow @FarmTeam."
        )

        self.assertEqual(
            protected.text,
            "Contact ZXQNT0QXZ, visit ZXQNT1QXZ, or follow ZXQNT2QXZ.",
        )
        self.assertEqual(
            restore_protected_text(protected.text, protected.replacements),
            "Contact rivera@agro-alimentarias.coop, visit https://example.org/page, or follow @FarmTeam.",
        )

        self.assertEqual(
            restore_protected_text(
                "Contact ZXQNT 0 QXZ, old OLPROTECTED1, translated OLPROTEGIDO2.",
                protected.replacements,
            ),
            "Contact rivera@agro-alimentarias.coop, old https://example.org/page, translated @FarmTeam.",
        )

    def test_contact_identity_text_is_preserved_without_translation(self) -> None:
        self.assertTrue(
            is_contact_identity_text("Martina Jurjevic Varga, ZXQNT0QXZ")
        )
        self.assertTrue(
            is_contact_identity_text(
                "Further information Case study coordinator: Martina Belovic Kelemen, ZXQNT0QXZ"
            )
        )
        self.assertFalse(is_contact_identity_text("Contact ZXQNT0QXZ"))
        self.assertFalse(
            is_contact_identity_text(
                "Read the full report and supporting documentation at ZXQNT0QXZ"
            )
        )

    def test_protected_only_text_is_not_translatable(self) -> None:
        self.assertFalse(
            has_unprotected_translatable_text(
                protect_nontranslatable_text("rivera@agro-alimentarias.coop").text
            )
        )
        self.assertFalse(
            has_unprotected_translatable_text(
                protect_nontranslatable_text("https://example.org/page @FarmTeam").text
            )
        )
        self.assertTrue(
            has_unprotected_translatable_text(
                protect_nontranslatable_text("Contact https://example.org/page").text
            )
        )

    def test_large_title_redaction_does_not_remove_author_line(self) -> None:
        doc = fitz.open()
        try:
            page = doc.new_page(width=600, height=400)
            page.insert_textbox(fitz.Rect(72, 80, 520, 170), "ORIGINAL TITLE", fontsize=48)
            page.insert_text((72, 220), "AUTHOR LINE", fontsize=24)
            block = ExtractedTextBlock(
                block_id=1,
                page_index=0,
                bbox=(72, 80, 520, 170),
                text="ORIGINAL TITLE",
                source="native",
                kind="title",
                confidence=1.0,
                style=TextStyleHint(font_name="helv", font_size=48.0, color_rgb=(0, 0, 0)),
                line_count=2,
            )

            _fit_and_write_block(page, block, "TRANSLATED TITLE")

            text = page.get_text()
            self.assertIn("AUTHOR LINE", text)
            self.assertNotIn("ORIGINAL TITLE", text)
        finally:
            doc.close()

    def test_narrow_line_expands_into_empty_space_to_fit_caption(self) -> None:
        doc = fitz.open()
        try:
            page = doc.new_page(width=420, height=180)
            source_rect = fitz.Rect(150, 80, 225, 91)
            page.insert_textbox(source_rect, "Fig 1 and 2", fontsize=9.0)
            block = ExtractedTextBlock(
                block_id=3,
                page_index=0,
                bbox=tuple(source_rect),
                text="Fig 1 and 2",
                source="native",
                kind="line",
                confidence=1.0,
                style=TextStyleHint(font_name="helv", font_size=9.0, color_rgb=(0, 0, 0)),
                line_count=1,
            )

            status = _fit_and_write_block(
                page,
                block,
                "Fig. 1 and 2: Agenskalns food distribution hub",
                obstacle_rects=[source_rect],
            )

            self.assertEqual(status, "fit")
            self.assertIn("Agenskalns", page.get_text())
        finally:
            doc.close()

    def test_tight_line_redaction_does_not_remove_contact_line_below(self) -> None:
        doc = fitz.open()
        try:
            page = doc.new_page(width=420, height=180)
            page.insert_textbox(
                fitz.Rect(72, 80, 300, 96),
                "Agro-alimentarias de Espana:",
                fontsize=7.0,
            )
            page.insert_textbox(
                fitz.Rect(72, 93, 320, 108),
                "rivera@agro-alimentarias.coop",
                fontsize=7.0,
            )
            block = ExtractedTextBlock(
                block_id=2,
                page_index=0,
                bbox=(72, 80, 300, 96),
                text="Agro-alimentarias de Espana:",
                source="native",
                kind="line",
                confidence=1.0,
                style=TextStyleHint(font_name="helv", font_size=7.0, color_rgb=(0, 0, 0)),
                line_count=1,
            )

            status = _fit_and_write_block(
                page,
                block,
                "Agrar- und Lebensmittelsektor:",
                protected_rects=[fitz.Rect(72, 93, 320, 108)],
            )

            text = page.get_text().replace("\n", " ")
            self.assertEqual(status, "fit")
            self.assertIn("rivera@agro-alimentarias.coop", text)
        finally:
            doc.close()

    def test_direct_pdf_translation_skips_pure_contact_blocks(self) -> None:
        class FakeTranslator:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def translate_single_strict(self, text: str, source_lang: str, target_lang: str) -> str:
                self.calls.append(text)
                return "Ubersetzter Agrartext"

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_in = Path(tmpdir) / "contact-source.pdf"
            pdf_out = Path(tmpdir) / "contact-translated.pdf"
            doc = fitz.open()
            try:
                page = doc.new_page(width=420, height=240)
                page.insert_text((72, 72), "Agricultural training methods", fontsize=11.0)
                page.insert_text((72, 120), "Martina Jurjevic Varga, martina.j.varga@pp-medvednica.hr", fontsize=9.0)
                page.insert_text((72, 145), "rivera@agro-alimentarias.coop", fontsize=9.0)
                doc.save(pdf_in)
            finally:
                doc.close()

            fake = FakeTranslator()
            with patch("app.pipeline.translate_pdf_direct.get_translator", return_value=fake):
                stats = translate_pdf_direct(pdf_in, pdf_out, target_lang="de", source_lang="en")

            self.assertEqual(stats.api_calls, 1)
            self.assertEqual(fake.calls, ["Agricultural training methods"])

            translated = fitz.open(pdf_out)
            try:
                text = translated[0].get_text().replace("\n", " ")
                self.assertIn("Ubersetzter Agrartext", text)
                self.assertIn("Martina Jurjevic Varga, martina.j.varga@pp-medvednica.hr", text)
                self.assertIn("rivera@agro-alimentarias.coop", text)
            finally:
                translated.close()

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

    def test_restore_page_links_does_not_duplicate_existing_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "link-test.pdf"
            doc = fitz.open()
            try:
                page = doc.new_page()
                page.insert_text((72, 72), "Example")
                page.insert_link(
                    {
                        "kind": fitz.LINK_URI,
                        "from": fitz.Rect(72, 60, 120, 80),
                        "uri": "https://example.com",
                    }
                )
                doc.save(pdf_path)
            finally:
                doc.close()

            reopened = fitz.open(pdf_path)
            try:
                page = reopened[0]
                captured = _capture_page_links(page)
                self.assertEqual(len(captured), 1)

                _restore_page_links(page, captured)

                self.assertEqual(len(page.get_links()), 1)
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
