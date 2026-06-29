from __future__ import annotations

import unittest

import deepl

from app.core.engines import UnsupportedDeepLLanguageError
from app.pipeline.translator_adaptive import AdaptiveTranslator


class _RecordingLLM:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.batch_size = 50

    def detect_language(self, samples, metadata_language=None):
        self.calls.append("detect")
        return "en"

    def translate_single_strict(self, text, source_lang, target_lang):
        self.calls.append("single")
        return f"LLM:{text}"

    def translate_strings_batch(self, strings, source_lang, target_lang):
        self.calls.append("batch")
        return {i: f"LLM:{s}" for i, s in enumerate(strings)}

    def translate_nodes(self, nodes, source_lang, target_lang):
        self.calls.append("nodes")
        return {}


class _DeepLStub:
    """DeepL stand-in whose translate methods raise a configured exception."""

    def __init__(self, exc=None) -> None:
        self.exc = exc
        self.batch_size = 40
        self.single_calls = 0

    def _maybe_raise(self):
        if self.exc is not None:
            raise self.exc

    def detect_language(self, samples, metadata_language=None):
        self._maybe_raise()
        return "de"

    def translate_single_strict(self, text, source_lang, target_lang):
        self.single_calls += 1
        self._maybe_raise()
        return f"DEEPL:{text}"

    def translate_strings_batch(self, strings, source_lang, target_lang):
        self._maybe_raise()
        return {i: f"DEEPL:{s}" for i, s in enumerate(strings)}

    def translate_nodes(self, nodes, source_lang, target_lang):
        self._maybe_raise()
        return {}


class AdaptiveTranslatorTests(unittest.TestCase):
    def test_uses_deepl_when_healthy(self) -> None:
        llm = _RecordingLLM()
        adaptive = AdaptiveTranslator(_DeepLStub(), lambda: llm)
        self.assertEqual(adaptive.translate_single_strict("hi", "en", "de"), "DEEPL:hi")
        self.assertEqual(llm.calls, [])

    def test_falls_back_to_llm_on_deepl_error(self) -> None:
        llm = _RecordingLLM()
        adaptive = AdaptiveTranslator(_DeepLStub(deepl.DeepLException("boom")), lambda: llm)
        self.assertEqual(adaptive.translate_single_strict("hi", "en", "de"), "LLM:hi")
        self.assertIn("single", llm.calls)

    def test_quota_error_is_sticky(self) -> None:
        llm = _RecordingLLM()
        stub = _DeepLStub(deepl.exceptions.QuotaExceededException("limit"))
        adaptive = AdaptiveTranslator(stub, lambda: llm)

        adaptive.translate_single_strict("a", "en", "de")  # first failure trips DeepL
        adaptive.translate_strings_batch(["b"], "en", "de")  # should skip DeepL entirely

        self.assertTrue(adaptive._deepl_down)
        self.assertEqual(stub.single_calls, 1)  # DeepL not retried after going down
        self.assertEqual(llm.calls, ["single", "batch"])

    def test_unsupported_language_falls_back_without_sticky(self) -> None:
        llm = _RecordingLLM()
        stub = _DeepLStub(UnsupportedDeepLLanguageError("no maltese"))
        adaptive = AdaptiveTranslator(stub, lambda: llm)

        self.assertEqual(adaptive.translate_single_strict("x", "en", "mt"), "LLM:x")
        self.assertFalse(adaptive._deepl_down)  # not a service outage

    def test_llm_factory_is_lazy(self) -> None:
        created = []

        def factory():
            created.append(1)
            return _RecordingLLM()

        adaptive = AdaptiveTranslator(_DeepLStub(), factory)
        adaptive.translate_single_strict("hi", "en", "de")
        self.assertEqual(created, [])  # DeepL healthy => LLM never built


if __name__ == "__main__":
    unittest.main()
