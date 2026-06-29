from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.core.engines import (
    UnsupportedDeepLLanguageError,
    deepl_source_code,
    deepl_target_code,
    default_engine,
    is_deepl_supported,
    validate_engine,
)


class EngineSelectionTests(unittest.TestCase):
    def test_validate_engine_accepts_known_values(self) -> None:
        self.assertEqual(validate_engine("llm"), "llm")
        self.assertEqual(validate_engine("DeepL"), "deepl")
        self.assertEqual(validate_engine(" adaptive "), "adaptive")

    def test_validate_engine_rejects_unknown(self) -> None:
        with self.assertRaises(ValueError):
            validate_engine("google")

    def test_validate_engine_none_uses_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(validate_engine(None), "llm")
        with patch.dict(os.environ, {"TRANSLATION_ENGINE": "deepl"}, clear=True):
            self.assertEqual(validate_engine(None), "deepl")
            self.assertEqual(default_engine(), "deepl")

    def test_default_engine_falls_back_on_garbage(self) -> None:
        with patch.dict(os.environ, {"TRANSLATION_ENGINE": "nonsense"}, clear=True):
            self.assertEqual(default_engine(), "llm")


class DeepLLanguageMappingTests(unittest.TestCase):
    def test_target_variants_for_en_and_pt(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(deepl_target_code("en"), "EN-GB")
            self.assertEqual(deepl_target_code("pt"), "PT-PT")

    def test_target_variants_are_configurable(self) -> None:
        env = {"DEEPL_EN_VARIANT": "EN-US", "DEEPL_PT_VARIANT": "PT-BR"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(deepl_target_code("en"), "EN-US")
            self.assertEqual(deepl_target_code("pt"), "PT-BR")

    def test_plain_target_codes_are_uppercased(self) -> None:
        self.assertEqual(deepl_target_code("de"), "DE")
        self.assertEqual(deepl_target_code("EL"), "EL")

    def test_source_codes_are_regionless_upper(self) -> None:
        self.assertEqual(deepl_source_code("en-GB"), "EN")
        self.assertEqual(deepl_source_code("pt"), "PT")

    def test_unsupported_languages(self) -> None:
        self.assertFalse(is_deepl_supported("mt"))
        self.assertFalse(is_deepl_supported("ga"))
        self.assertTrue(is_deepl_supported("de"))

    def test_target_code_raises_for_unsupported(self) -> None:
        with self.assertRaises(UnsupportedDeepLLanguageError):
            deepl_target_code("mt")


if __name__ == "__main__":
    unittest.main()
