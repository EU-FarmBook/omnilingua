from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import fitz

from app.pipeline.block_schema import ExtractedTextBlock, TextStyleHint
from app.pipeline.fonts import sanitize_text_for_rendering
from app.pipeline.protected_text import (
    contains_protected_token,
    has_unprotected_translatable_text,
    is_contact_identity_text,
    protect_nontranslatable_text,
    restore_protected_text,
)
from app.pipeline.translate_pdf_direct import (
    _BlockWritePlan,
    _capture_page_links,
    _fit_and_write_block,
    _harmonize_plan_font_sizes,
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
        self.assertTrue(contains_protected_token("ZXQNT0QXZ"))
        self.assertFalse(contains_protected_token("rivera@agro-alimentarias.coop"))

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

    def test_harmonize_pulls_siblings_to_one_size_but_spares_outlier(self) -> None:
        def plan(size: float, key: tuple) -> _BlockWritePlan:
            return _BlockWritePlan(
                redaction_rect=fitz.Rect(0, 0, 1, 1),
                placed_rect=fitz.Rect(0, 0, 1, 1),
                render_text="x",
                fontname="helv",
                fontfile=None,
                fontsize=size,
                line_height=1.1,
                color=(0, 0, 0),
                harmonize_key=key,
            )

        body = ("body", 0, 10)
        plans = {
            0: [plan(10.0, body), plan(10.0, body), plan(9.5, body), plan(6.5, body)],
        }
        out = _harmonize_plan_font_sizes(plans)[0]
        sizes = [round(p.fontsize, 2) for p in out]
        # Median of [10,10,9.5,6.5] = 9.75; floor = 9.75*0.85 = 8.29; group min = 6.5;
        # target = max(6.5, 8.29) = 8.29. The three >=8.29 collapse to it; the 6.5
        # dense outlier is left untouched (it cannot reach the shared size).
        self.assertEqual(sizes.count(round(9.75 * 0.85, 2)), 3)
        self.assertIn(6.5, sizes)

    def test_harmonize_leaves_small_groups_untouched(self) -> None:
        def plan(size: float, key: tuple) -> _BlockWritePlan:
            return _BlockWritePlan(
                redaction_rect=fitz.Rect(0, 0, 1, 1),
                placed_rect=fitz.Rect(0, 0, 1, 1),
                render_text="x",
                fontname="helv",
                fontfile=None,
                fontsize=size,
                line_height=1.1,
                color=(0, 0, 0),
                harmonize_key=key,
            )

        # Only two members — below the minimum for a shared size, left as-is.
        plans = {0: [plan(11.0, ("caption", 1, 9)), plan(8.0, ("caption", 1, 9))]}
        out = _harmonize_plan_font_sizes(plans)[0]
        self.assertEqual(sorted(p.fontsize for p in out), [8.0, 11.0])

    def test_vertical_text_keeps_orientation_after_translation(self) -> None:
        class FakeTranslator:
            def translate_single_strict(self, text: str, source_lang: str, target_lang: str) -> str:
                if "Practice" in text:
                    return "Praktilise kokkuvotte number"
                return "Vee desinfitseerimine parandab bioturvalisust."

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_in = Path(tmpdir) / "vertical-source.pdf"
            pdf_out = Path(tmpdir) / "vertical-translated.pdf"
            doc = fitz.open()
            try:
                page = doc.new_page(width=420, height=400)
                page.insert_textbox(
                    fitz.Rect(40, 60, 62, 360),
                    "Practice Abstract number nineteen",
                    fontsize=10.0,
                    rotate=90,
                )
                page.insert_text((110, 90), "Water disinfection improves farm biosecurity.", fontsize=11.0)
                doc.save(pdf_in)
            finally:
                doc.close()

            with patch("app.pipeline.translate_pdf_direct.get_translator", return_value=FakeTranslator()):
                translate_pdf_direct(pdf_in, pdf_out, target_lang="et", source_lang="en")

            translated = fitz.open(pdf_out)
            try:
                vertical_dirs = [
                    line["dir"]
                    for block in translated[0].get_text("dict")["blocks"]
                    for line in block.get("lines", [])
                    if "kokkuvotte" in "".join(s["text"] for s in line["spans"])
                ]
            finally:
                translated.close()
            self.assertTrue(vertical_dirs, "vertical block was not translated/placed")
            for direction in vertical_dirs:
                self.assertAlmostEqual(direction[0], 0.0, places=2)
                self.assertAlmostEqual(direction[1], -1.0, places=2)

    def test_untranslated_neighbor_source_text_survives_redactions(self) -> None:
        # A block whose translation is rejected keeps its source text; a placed
        # neighbour's redaction (adjacent line boxes overlap by a few points)
        # must not erase glyphs out of that preserved text.
        class FakeTranslator:
            def translate_single_strict(self, text: str, source_lang: str, target_lang: str) -> str:
                if text.startswith("REJECTME"):
                    return ""
                return "Ubersetzte landwirtschaftliche Zeile"

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_in = Path(tmpdir) / "preserve-source.pdf"
            pdf_out = Path(tmpdir) / "preserve-translated.pdf"
            doc = fitz.open()
            try:
                page = doc.new_page(width=420, height=240)
                # Different font sizes prevent merging into one paragraph; the
                # tight leading makes the two line bboxes overlap vertically, so
                # the first line's redaction would previously clip the second.
                page.insert_text((72, 83), "Sustainable soil management for arable farms", fontsize=11.0)
                page.insert_text((72, 90), "REJECTME preserved paradigm shift sentence", fontsize=9.0)
                doc.save(pdf_in)
            finally:
                doc.close()

            with patch("app.pipeline.translate_pdf_direct.get_translator", return_value=FakeTranslator()):
                translate_pdf_direct(pdf_in, pdf_out, target_lang="de", source_lang="en")

            translated = fitz.open(pdf_out)
            try:
                text = translated[0].get_text().replace("\n", " ")
            finally:
                translated.close()
            self.assertIn("Ubersetzte landwirtschaftliche Zeile", text)
            self.assertIn("REJECTME preserved paradigm shift sentence", text)

    def test_direct_pdf_translation_retries_hallucinated_protection_token(self) -> None:
        class FakeTranslator:
            def __init__(self) -> None:
                self.calls = 0

            def translate_single_strict(self, text: str, source_lang: str, target_lang: str) -> str:
                self.calls += 1
                if self.calls == 1:
                    return "Fehlerhafte ZXQNT0QXZ"
                return "Saubere Ubersetzung"

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_in = Path(tmpdir) / "source.pdf"
            pdf_out = Path(tmpdir) / "translated.pdf"
            doc = fitz.open()
            try:
                page = doc.new_page(width=420, height=180)
                page.insert_text((72, 72), "Agricultural market improves local access", fontsize=11.0)
                doc.save(pdf_in)
            finally:
                doc.close()

            fake = FakeTranslator()
            with patch("app.pipeline.translate_pdf_direct.get_translator", return_value=fake):
                stats = translate_pdf_direct(pdf_in, pdf_out, target_lang="de", source_lang="en")

            self.assertEqual(stats.api_calls, 2)
            self.assertEqual(stats.blocks_retried, 1)
            self.assertEqual(stats.blocks_rejected, 0)
            translated = fitz.open(pdf_out)
            try:
                text = translated[0].get_text().replace("\n", " ")
                self.assertIn("Saubere Ubersetzung", text)
                self.assertNotIn("ZXQNT", text)
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
