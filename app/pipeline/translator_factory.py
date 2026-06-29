from __future__ import annotations

from typing import Optional

from app.core.engines import validate_engine
from app.pipeline.translator_llm import LLMTranslator


def get_translator(engine: Optional[str] = None):
    """Return a translator for the selected engine.

    ``engine`` is one of ``llm`` / ``deepl`` / ``adaptive``; ``None`` resolves to the
    ``TRANSLATION_ENGINE`` env default (``llm``). DeepL-backed engines are imported
    lazily so the LLM-only path never requires the ``deepl`` dependency at call time.
    """
    resolved = validate_engine(engine)

    if resolved == "llm":
        return LLMTranslator()

    if resolved == "deepl":
        from app.pipeline.translator_deepl import DeepLTranslator

        return DeepLTranslator()

    # adaptive
    from app.pipeline.translator_adaptive import AdaptiveTranslator
    from app.pipeline.translator_deepl import DeepLTranslator

    return AdaptiveTranslator(DeepLTranslator(), LLMTranslator)
