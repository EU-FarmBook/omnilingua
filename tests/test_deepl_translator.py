from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.core.engines import UnsupportedDeepLLanguageError


class _FakeResult:
    def __init__(self, text: str, detected: str = "EN") -> None:
        self.text = text
        self.detected_source_language = detected


class _FakeDeepLClient:
    """Minimal stand-in for deepl.Translator capturing the last call."""

    def __init__(self, *args, **kwargs) -> None:
        self.last_kwargs = None
        self.last_text = None

    def translate_text(self, text, **kwargs):
        self.last_text = text
        self.last_kwargs = kwargs
        if isinstance(text, list):
            return [_FakeResult(f"[{kwargs.get('target_lang')}] {t}") for t in text]
        return _FakeResult(f"[{kwargs.get('target_lang')}] {text}", detected="DE")


def _make_translator():
    from app.pipeline.translator_deepl import DeepLTranslator

    return DeepLTranslator()


class DeepLTranslatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = patch.dict(os.environ, {"DEEPL_API_KEY": "test-key"}, clear=True)
        self._env.start()
        self._client_patch = patch("deepl.Translator", _FakeDeepLClient)
        self._client_patch.start()

    def tearDown(self) -> None:
        self._client_patch.stop()
        self._env.stop()

    def test_requires_api_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                _make_translator()

    def test_translate_single_strict(self) -> None:
        translator = _make_translator()
        out = translator.translate_single_strict("Hello", "en", "de")
        self.assertEqual(out, "[DE] Hello")
        self.assertEqual(translator.client.last_kwargs["target_lang"], "DE")
        self.assertEqual(translator.client.last_kwargs["source_lang"], "EN")

    def test_translate_single_strict_empty_returns_none(self) -> None:
        translator = _make_translator()
        self.assertIsNone(translator.translate_single_strict("   ", "en", "de"))

    def test_translate_strings_batch_keeps_indexes(self) -> None:
        translator = _make_translator()
        out = translator.translate_strings_batch(["a", "  ", "b"], "en", "fr")
        self.assertEqual(out, {0: "[FR] a", 2: "[FR] b"})

    def test_unsupported_target_raises(self) -> None:
        translator = _make_translator()
        with self.assertRaises(UnsupportedDeepLLanguageError):
            translator.translate_single_strict("Hello", "en", "mt")
        with self.assertRaises(UnsupportedDeepLLanguageError):
            translator.translate_strings_batch(["Hello"], "en", "ga")

    def test_detect_language_uses_metadata_shortcut(self) -> None:
        translator = _make_translator()
        self.assertEqual(translator.detect_language(["whatever"], metadata_language="fr"), "fr")

    def test_detect_language_from_api(self) -> None:
        translator = _make_translator()
        self.assertEqual(translator.detect_language(["Some German sentence here."]), "de")


if __name__ == "__main__":
    unittest.main()
