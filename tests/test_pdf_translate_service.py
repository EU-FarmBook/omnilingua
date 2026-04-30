from __future__ import annotations

import unittest

from fastapi import HTTPException

from app.services.pdf_translate_service import normalize_optional_text, validate_request


class PdfTranslateServiceValidationTests(unittest.TestCase):
    def test_normalize_optional_text_converts_blank_to_none(self) -> None:
        self.assertIsNone(normalize_optional_text(None))
        self.assertIsNone(normalize_optional_text(""))
        self.assertIsNone(normalize_optional_text("   "))
        self.assertEqual(normalize_optional_text(" el "), "el")

    def test_validate_request_requires_target_lang_without_mapping(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_request("example.pdf", None, None, "html", None)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("target_lang is required", ctx.exception.detail)

    def test_validate_request_rejects_same_source_and_target(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_request("example.pdf", "en", "en", "html", None)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("must be different", ctx.exception.detail)

    def test_validate_request_rejects_unsupported_language(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_request("example.pdf", "xx", None, "html", None)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("not supported", ctx.exception.detail)

    def test_validate_request_normalizes_valid_codes(self) -> None:
        target_lang, source_lang = validate_request(
            "example.pdf",
            " EL ",
            "en-GB",
            "html",
            None,
        )

        self.assertEqual(target_lang, "el")
        self.assertEqual(source_lang, "en")

    def test_validate_request_allows_mapping_json_without_target(self) -> None:
        target_lang, source_lang = validate_request(
            "example.pdf",
            None,
            None,
            "html",
            '{"Hello":"Hola"}',
        )

        self.assertIsNone(target_lang)
        self.assertIsNone(source_lang)


if __name__ == "__main__":
    unittest.main()
