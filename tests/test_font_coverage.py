from __future__ import annotations

import unittest
from pathlib import Path

import fitz

from app.core.languages import SUPPORTED_EU_LANGUAGE_CODES
from app.pipeline.block_schema import ExtractedTextBlock, TextStyleHint
from app.pipeline.fonts import (
    needs_unicode_font,
    resolve_font_for_text,
    sanitize_text_for_rendering,
)
from app.pipeline.translate_pdf_direct import _fit_and_write_block


# One representative string per EU language, chosen to include that language's
# accented / non-Latin characters.
EU_SAMPLES = {
    "bg": "Бърза кафява лисица",
    "cs": "Příliš žluťoučký kůň úpěl",
    "da": "Quizdeltagerne spiste jordbær",
    "de": "Grüße über die Straßen",
    "el": "Καλημέρα κόσμε, ωραία μέρα",
    "en": "The quick brown fox",
    "es": "El veloz murciélago añejo",
    "et": "Põdra õhtu jäääär",
    "fi": "Törkylempijävongahdus äöå",
    "fr": "Voix ambiguë de cœur déçu",
    "ga": "Chuaigh bé mhór á dhó",
    "hr": "Đačko društvo čeka šuma",
    "hu": "Árvíztűrő tükörfúrógép",
    "it": "Mangià però è perché",
    "lt": "Ąžuolas šaltyšius ūžia",
    "lv": "Ūdensšķīvis ģērbjas",
    "mt": "Ċensiment ħġieġ żraben għaġel",
    "nl": "Pa's wijze lynx bezag",
    "pl": "Zażółć gęślą jaźń",
    "pt": "Olá, coração e ação",
    "ro": "Înălțimea școlii bătrâne",
    "sk": "Kŕdeľ šťastných ďatľov",
    "sl": "Šerif že čaka ob cesti",
    "sv": "Flygande bäckasiner söka",
}

DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _render_and_extract(text: str) -> str:
    """Render ``text`` the way the direct engine does, then read it back."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=120)
    style = TextStyleHint(font_name="Helvetica", font_size=12.0, color_rgb=(0, 0, 0))
    rect = fitz.Rect(10, 10, 390, 110)
    fontname, fontfile, render_text = resolve_font_for_text(page, style, text)
    page.insert_textbox(rect, render_text, fontname=fontname, fontfile=fontfile, fontsize=12)
    extracted = page.get_text().replace("\n", " ").strip()
    doc.close()
    return extracted


class FontCoverageTests(unittest.TestCase):
    def test_all_24_eu_languages_have_samples(self) -> None:
        self.assertEqual(set(EU_SAMPLES), set(SUPPORTED_EU_LANGUAGE_CODES))

    def test_extended_latin_triggers_unicode_font(self) -> None:
        # Regression guard: Latin Extended-A/B must NOT fall through to base-14 Helvetica.
        for code in ("pl", "cs", "sk", "hu", "ro", "lt", "lv", "hr", "sl", "mt"):
            self.assertTrue(
                needs_unicode_font(EU_SAMPLES[code]),
                f"{code} should require the Unicode fallback font",
            )

    @unittest.skipUnless(Path(DEJAVU).exists(), "DejaVuSans fallback font not installed")
    def test_every_eu_language_round_trips_without_notdef(self) -> None:
        for code, text in EU_SAMPLES.items():
            expected = sanitize_text_for_rendering(text)
            extracted = _render_and_extract(text)
            self.assertNotIn("?", extracted, f"{code}: notdef '?' rendered for {text!r}")
            self.assertEqual(extracted, expected, f"{code}: render mismatch for {text!r}")


class LayoutFitStatusTests(unittest.TestCase):
    def _block(self, bbox, kind="line", font_size=11.0):
        return ExtractedTextBlock(
            block_id=1, page_index=0, bbox=bbox, text="source",
            source="native", kind=kind, confidence=1.0,
            style=TextStyleHint(font_name="Helvetica", font_size=font_size, color_rgb=(0, 0, 0)),
            line_count=1,
        )

    def test_short_text_fits(self) -> None:
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        status = _fit_and_write_block(page, self._block((40, 100, 400, 130)), "Short line.")
        self.assertEqual(status, "fit")
        doc.close()

    def test_overlong_text_in_tight_box_preserves_source_when_unplaced(self) -> None:
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((40, 109), "source", fontsize=8.0)
        tight = self._block((40, 100, 150, 112), kind="caption", font_size=9.0)
        long_tr = (
            "Wasserverbrauch pro Tonne verarbeitetem landwirtschaftlichem Material unter "
            "Berücksichtigung saisonaler Schwankungen und regionaler Unterschiede in der "
            "Bewässerungsinfrastruktur der gesamten Region."
        )
        status = _fit_and_write_block(page, tight, long_tr)
        self.assertEqual(status, "unplaced")
        self.assertIn("source", page.get_text())
        doc.close()

    def test_degenerate_box_is_skipped_without_redaction(self) -> None:
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        status = _fit_and_write_block(page, self._block((40, 100, 41, 101)), "anything")
        self.assertEqual(status, "skipped")
        doc.close()


if __name__ == "__main__":
    unittest.main()
