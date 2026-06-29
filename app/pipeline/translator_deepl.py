from __future__ import annotations

import os
from typing import Dict, List, Optional

import deepl

from app.core.engines import (
    UnsupportedDeepLLanguageError,
    deepl_source_code,
    deepl_target_code,
    is_deepl_supported,
)
from app.core.languages import (
    EU_LANGUAGE_NAMES,
    SUPPORTED_EU_LANGUAGE_CODES,
    normalize_language_code,
)
from app.core.model_config import get_deepl_config


class DeepLTranslator:
    """DeepL-backed translator matching the LLMTranslator contract.

    Implements ``detect_language``, ``translate_strings_batch``,
    ``translate_single_strict`` and ``translate_nodes`` so it is a drop-in peer of
    :class:`app.pipeline.translator_llm.LLMTranslator`.
    """

    def __init__(self) -> None:
        config = get_deepl_config()
        if not config.api_key:
            raise RuntimeError(
                "DEEPL_API_KEY is not set; cannot use the DeepL translation engine."
            )
        self.client = deepl.Translator(config.api_key, server_url=config.server_url)
        self.batch_size = int(os.getenv("DEEPL_BATCH_SIZE", os.getenv("LLM_BATCH_SIZE", "50")))

    def _ensure_supported(self, target_lang: str) -> None:
        if not is_deepl_supported(target_lang):
            name = EU_LANGUAGE_NAMES.get(normalize_language_code(target_lang), target_lang)
            raise UnsupportedDeepLLanguageError(
                f"DeepL does not support translation into {name} ('{target_lang}'). "
                f"Use engine 'llm' or 'adaptive' for this language."
            )

    def _source(self, source_lang: Optional[str]) -> Optional[str]:
        return deepl_source_code(source_lang) if source_lang else None

    def _translate_texts(
        self,
        texts: List[str],
        source_lang: Optional[str],
        target_lang: str,
    ) -> List[str]:
        results = self.client.translate_text(
            texts,
            source_lang=self._source(source_lang),
            target_lang=deepl_target_code(target_lang),
        )
        if not isinstance(results, list):
            results = [results]
        return [(result.text or "").strip() for result in results]

    def detect_language(
        self,
        text_samples: List[str],
        metadata_language: Optional[str] = None,
    ) -> str:
        if metadata_language:
            code = normalize_language_code(metadata_language)
            if code in SUPPORTED_EU_LANGUAGE_CODES:
                return code

        samples = [text.strip() for text in text_samples if text and text.strip()]
        if not samples:
            return "en"

        result = self.client.translate_text(samples[0][:200], target_lang="EN-US")
        detected = normalize_language_code(result.detected_source_language or "")
        return detected if detected in SUPPORTED_EU_LANGUAGE_CODES else "en"

    def translate_single_strict(
        self,
        source_text: str,
        source_lang: str,
        target_lang: str,
    ) -> Optional[str]:
        if not source_text or not source_text.strip():
            return None
        self._ensure_supported(target_lang)
        translated = self._translate_texts([source_text], source_lang, target_lang)
        text = translated[0] if translated else ""
        return text or None

    def translate_strings_batch(
        self,
        strings: List[str],
        source_lang: str,
        target_lang: str,
    ) -> Dict[int, str]:
        self._ensure_supported(target_lang)
        indexed = [(index, text) for index, text in enumerate(strings) if text and text.strip()]
        if not indexed:
            return {}

        translated = self._translate_texts([text for _, text in indexed], source_lang, target_lang)
        out: Dict[int, str] = {}
        for (original_index, _), text in zip(indexed, translated):
            if text:
                out[original_index] = text
        return out

    def translate_nodes(self, nodes, source_lang: str, target_lang: str) -> Dict[int, str]:
        self._ensure_supported(target_lang)
        indexed = [
            (node.node_id, node.stripped_text)
            for node in nodes
            if node.stripped_text and node.stripped_text.strip()
        ]
        if not indexed:
            return {}

        translated = self._translate_texts([text for _, text in indexed], source_lang, target_lang)
        out: Dict[int, str] = {}
        for (node_id, _), text in zip(indexed, translated):
            if text:
                out[node_id] = text
        return out
