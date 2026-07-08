from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF


FORMULA_HEAVY_MESSAGE = (
    "PDF translation is not supported for formula-heavy or equation-heavy documents."
)


class PdfContentPolicyError(ValueError):
    """Raised when a PDF is outside the supported translation content policy."""


@dataclass(frozen=True)
class PdfContentPolicyResult:
    pages_total: int
    text_lines_total: int
    formula_lines_total: int
    formula_line_ratio: float
    pages_with_formula_lines: int
    max_formula_lines_on_page: int
    allowed: bool
    reason: str | None = None


_FORMULA_SYMBOL_RE = re.compile(r"[=∑∫√≤≥≈≠∞∂∆∇±×÷→←↔⇒⇔^_{}<>|]")
_EQUATION_NUMBER_RE = re.compile(r"(?:^|\s)\(\d+(?:\.\d+)*\)\s*$")
_WORD_RE = re.compile(r"\b[A-Za-zÀ-ÖØ-öø-ÿ]{3,}\b")
_MATH_FUNCTION_RE = re.compile(
    r"\b(?:sin|cos|tan|log|ln|lim|max|min|argmax|argmin|exp|sqrt|var|cov|Pr)\s*(?:\(|_)"
)


def _normalized_lines(page: fitz.Page) -> list[str]:
    return [
        " ".join(line.split()).strip()
        for line in page.get_text("text").splitlines()
        if line.strip()
    ]


def _is_formula_like_line(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) < 3:
        return False

    symbol_hits = len(_FORMULA_SYMBOL_RE.findall(stripped))
    digit_hits = sum(1 for ch in stripped if ch.isdigit())
    alpha_hits = sum(1 for ch in stripped if ch.isalpha())
    word_hits = len(_WORD_RE.findall(stripped))
    non_space = sum(1 for ch in stripped if not ch.isspace())
    if non_space == 0:
        return False

    has_equation_number = bool(_EQUATION_NUMBER_RE.search(stripped))
    has_math_function = bool(_MATH_FUNCTION_RE.search(stripped))

    if has_equation_number and (symbol_hits >= 1 or digit_hits >= 2):
        return True
    if has_math_function and (symbol_hits >= 1 or digit_hits >= 1):
        return True
    if symbol_hits >= 3:
        return True

    symbolic_density = (symbol_hits + digit_hits) / non_space
    if symbol_hits >= 1 and symbolic_density >= 0.35 and word_hits <= 3:
        return True
    if symbol_hits >= 2 and alpha_hits <= digit_hits + symbol_hits and word_hits <= 4:
        return True

    return False


def assess_pdf_translation_eligibility(pdf_path: Path) -> PdfContentPolicyResult:
    doc = fitz.open(str(pdf_path))
    try:
        pages_total = len(doc)
        text_lines_total = 0
        formula_lines_total = 0
        pages_with_formula_lines = 0
        max_formula_lines_on_page = 0

        for page in doc:
            lines = _normalized_lines(page)
            text_lines_total += len(lines)
            page_formula_lines = sum(1 for line in lines if _is_formula_like_line(line))
            formula_lines_total += page_formula_lines
            if page_formula_lines:
                pages_with_formula_lines += 1
                max_formula_lines_on_page = max(max_formula_lines_on_page, page_formula_lines)

        formula_line_ratio = (
            formula_lines_total / text_lines_total if text_lines_total else 0.0
        )

        reason = None
        if formula_lines_total >= 12 and formula_line_ratio >= 0.08:
            reason = "formula_line_density"
        elif (
            pages_total >= 3
            and formula_lines_total >= 8
            and pages_with_formula_lines / pages_total >= 0.25
        ):
            reason = "formula_spread_across_pages"
        elif formula_lines_total >= 12 and max_formula_lines_on_page >= 8:
            reason = "formula_dense_page"

        return PdfContentPolicyResult(
            pages_total=pages_total,
            text_lines_total=text_lines_total,
            formula_lines_total=formula_lines_total,
            formula_line_ratio=formula_line_ratio,
            pages_with_formula_lines=pages_with_formula_lines,
            max_formula_lines_on_page=max_formula_lines_on_page,
            allowed=reason is None,
            reason=reason,
        )
    finally:
        doc.close()


def ensure_pdf_translation_allowed(pdf_path: Path) -> None:
    result = assess_pdf_translation_eligibility(pdf_path)
    if not result.allowed:
        raise PdfContentPolicyError(FORMULA_HEAVY_MESSAGE)
