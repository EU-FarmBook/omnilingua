from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

import fitz
from fastapi import HTTPException

from app.services.document_translate_service import (
    run_document_translation,
    validate_document_request,
)


class _FakeUploadFile:
    def __init__(self, filename: str, data: bytes) -> None:
        self.filename = filename
        self._data = data

    async def read(self) -> bytes:
        return self._data


def _formula_heavy_pdf_bytes() -> bytes:
    doc = fitz.open()
    try:
        page = doc.new_page(width=595, height=842)
        for index in range(12):
            y = 72 + (index * 18)
            page.insert_text(
                (72, y),
                f"x_{index} = y_{index} + z_{index} ({index + 1})",
                fontsize=10,
            )
        return doc.tobytes()
    finally:
        doc.close()


class DocumentTranslateServiceTests(unittest.TestCase):
    def test_rejects_unsupported_extension(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_document_request("notes.md", "el", "en")

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Unsupported file type", ctx.exception.detail)

    def test_accepts_supported_extension_and_normalizes_languages(self) -> None:
        suffix, target_lang, source_lang, engine = validate_document_request("slides.PPTX", " EL ", "en-GB")

        self.assertEqual(suffix, ".pptx")
        self.assertEqual(target_lang, "el")
        self.assertEqual(source_lang, "en")
        self.assertEqual(engine, "llm")

    def test_rejects_same_source_and_target(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_document_request("report.docx", "el", "el")

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("must be different", ctx.exception.detail)

    def test_deepl_rejects_unsupported_language(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_document_request("report.docx", "ga", "en", "deepl")

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("DeepL does not support", ctx.exception.detail)

    def test_adaptive_allows_unsupported_language(self) -> None:
        _, target_lang, _, engine = validate_document_request("report.docx", "ga", "en", "adaptive")
        self.assertEqual(target_lang, "ga")
        self.assertEqual(engine, "adaptive")

    def test_formula_heavy_pdf_returns_400_before_translation(self) -> None:
        file = _FakeUploadFile("formula.pdf", _formula_heavy_pdf_bytes())

        with patch("app.pipeline.translate_pdf_direct.get_translator") as get_translator:
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(
                    run_document_translation(
                        file,
                        target_lang="de",
                        source_lang="en",
                        engine="llm",
                    )
                )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("formula-heavy", ctx.exception.detail)
        get_translator.assert_not_called()


if __name__ == "__main__":
    unittest.main()
