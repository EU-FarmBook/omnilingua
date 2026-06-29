from __future__ import annotations

import unittest

from fastapi import HTTPException

from app.services.document_translate_service import validate_document_request


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


if __name__ == "__main__":
    unittest.main()
