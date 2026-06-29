from __future__ import annotations

from typing import Callable

import deepl

from app.core.engines import UnsupportedDeepLLanguageError


# Errors that should trigger a fallback to the LLM translator.
_FALLBACK_ERRORS = (deepl.DeepLException, UnsupportedDeepLLanguageError, ConnectionError, OSError)


class AdaptiveTranslator:
    """Try DeepL first, fall back to the LLM on any DeepL error.

    A language that DeepL cannot handle (``UnsupportedDeepLLanguageError``) falls back
    per-call without disabling DeepL. A genuine service failure (quota exceeded, rate
    limit, auth/connection error) sets a sticky ``_deepl_down`` flag so the rest of the
    document goes straight to the LLM instead of repeatedly hitting an exhausted quota.
    """

    def __init__(self, deepl_translator, llm_factory: Callable[[], object]) -> None:
        self._deepl = deepl_translator
        self._llm_factory = llm_factory
        self._llm = None
        self._deepl_down = False
        self.batch_size = getattr(deepl_translator, "batch_size", 50)

    def _llm_translator(self):
        if self._llm is None:
            self._llm = self._llm_factory()
        return self._llm

    def _run(self, method: str, *args, **kwargs):
        if not self._deepl_down:
            try:
                return getattr(self._deepl, method)(*args, **kwargs)
            except _FALLBACK_ERRORS as exc:
                # A service-level failure disables DeepL for the rest of this run;
                # an unsupported-language error only falls back for this call.
                if not isinstance(exc, UnsupportedDeepLLanguageError):
                    self._deepl_down = True
        return getattr(self._llm_translator(), method)(*args, **kwargs)

    def detect_language(self, text_samples, metadata_language=None):
        return self._run("detect_language", text_samples, metadata_language=metadata_language)

    def translate_single_strict(self, source_text, source_lang, target_lang):
        return self._run("translate_single_strict", source_text, source_lang, target_lang)

    def translate_strings_batch(self, strings, source_lang, target_lang):
        return self._run("translate_strings_batch", strings, source_lang, target_lang)

    def translate_nodes(self, nodes, source_lang, target_lang):
        return self._run("translate_nodes", nodes, source_lang, target_lang)
