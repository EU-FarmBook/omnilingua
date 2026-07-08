from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from app.pipeline.pdf_content_policy import (
    PdfContentPolicyError,
    assess_pdf_translation_eligibility,
    ensure_pdf_translation_allowed,
)


def _write_pdf(path: Path, pages: list[list[str]]) -> None:
    doc = fitz.open()
    try:
        for page_lines in pages:
            page = doc.new_page(width=595, height=842)
            y = 72
            for line in page_lines:
                page.insert_text((72, y), line, fontsize=10)
                y += 18
        doc.save(path)
    finally:
        doc.close()


class PdfContentPolicyTests(unittest.TestCase):
    def test_allows_normal_prose_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "prose.pdf"
            _write_pdf(
                pdf_path,
                [
                    [
                        "This report explains the project goals and expected outcomes.",
                        "The document contains ordinary prose for translation.",
                        "It does not contain mathematical derivations or equations.",
                    ]
                ],
            )

            result = assess_pdf_translation_eligibility(pdf_path)

            self.assertTrue(result.allowed)
            self.assertEqual(result.formula_lines_total, 0)

    def test_allows_prose_pdf_with_a_couple_of_equations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "light_equations.pdf"
            _write_pdf(
                pdf_path,
                [
                    [
                        "The model is introduced for context and remains readable.",
                        "Yield = biomass / area (1)",
                        "The result section explains the trend in ordinary language.",
                        "Water use efficiency = output / input (2)",
                    ]
                ],
            )

            result = assess_pdf_translation_eligibility(pdf_path)

            self.assertTrue(result.allowed)
            self.assertLess(result.formula_lines_total, 8)

    def test_rejects_formula_heavy_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "formula_heavy.pdf"
            formula_lines = [
                "x_i = y_i + z_i (1)",
                "F(x) = ∫ x^2 dx (2)",
                "p_i = exp(x_i) / ∑ exp(x_j) (3)",
                "∂L / ∂w = 0 (4)",
                "A = {x | x ≥ 0} (5)",
                "E = mc^2 (6)",
                "r_t = α + β x_t + ε_t (7)",
                "lim x_n = x* (8)",
                "√a + √b ≈ c (9)",
                "∇ f(x) = 0 (10)",
                "x → y ⇔ y ≥ x (11)",
                "q_i = q_{i-1} + ∆q_i (12)",
                "m_i = a_i + b_i / c_i (13)",
                "s_t = p_t - p_{t-1} (14)",
            ]
            _write_pdf(pdf_path, [formula_lines])

            result = assess_pdf_translation_eligibility(pdf_path)

            self.assertFalse(result.allowed)
            with self.assertRaises(PdfContentPolicyError):
                ensure_pdf_translation_allowed(pdf_path)

    def test_allows_numeric_table_without_formula_syntax(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "table.pdf"
            _write_pdf(
                pdf_path,
                [
                    [
                        "Crop Yield Moisture Protein",
                        "Wheat 12.4 8.1 10.2",
                        "Barley 11.7 7.8 9.9",
                        "Maize 13.2 8.5 8.7",
                        "These values are tabular measurements, not equations.",
                    ]
                ],
            )

            result = assess_pdf_translation_eligibility(pdf_path)

            self.assertTrue(result.allowed)


if __name__ == "__main__":
    unittest.main()
