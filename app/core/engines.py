from __future__ import annotations

import os
from typing import Literal, Optional

from app.core.languages import (
    EU_LANGUAGE_NAMES,
    SUPPORTED_EU_LANGUAGE_CODES,
    normalize_language_code,
)
from app.core.model_config import get_deepl_config


TranslationEngine = Literal["llm", "deepl", "adaptive"]

VALID_ENGINES: frozenset[str] = frozenset({"llm", "deepl", "adaptive"})


class UnsupportedDeepLLanguageError(ValueError):
    """Raised when a target language is not available on DeepL."""


def default_engine() -> str:
    """Resolve the configured default engine (env ``TRANSLATION_ENGINE``)."""
    value = (os.getenv("TRANSLATION_ENGINE") or "").strip().lower()
    return value if value in VALID_ENGINES else "llm"


def validate_engine(value: Optional[str]) -> str:
    """Normalize and validate an engine selector, falling back to the default."""
    if value is None or not value.strip():
        return default_engine()

    engine = value.strip().lower()
    if engine not in VALID_ENGINES:
        raise ValueError(
            f"engine must be one of: {', '.join(sorted(VALID_ENGINES))}. Got '{value}'."
        )
    return engine


# Languages among the 24 EU codes that DeepL is known not to support. DeepL's own
# API is the ultimate arbiter (an unsupported target raises and is caught), but this
# lets us fail fast with a clear message instead of doing pointless work.
DEEPL_KNOWN_UNSUPPORTED: frozenset[str] = frozenset({"ga", "mt"})


def is_deepl_supported(code: str) -> bool:
    normalized = normalize_language_code(code)
    return (
        normalized in SUPPORTED_EU_LANGUAGE_CODES
        and normalized not in DEEPL_KNOWN_UNSUPPORTED
    )


def deepl_source_code(code: str) -> str:
    """Map an EU 2-letter code to a DeepL source-language code (regionless, upper)."""
    return normalize_language_code(code).upper()


def deepl_target_code(code: str) -> str:
    """Map an EU 2-letter code to a DeepL target-language code.

    DeepL requires a regional variant for English and Portuguese targets; the
    variants are configurable via ``DEEPL_EN_VARIANT`` / ``DEEPL_PT_VARIANT``.
    """
    normalized = normalize_language_code(code)
    if not is_deepl_supported(normalized):
        name = EU_LANGUAGE_NAMES.get(normalized, normalized)
        raise UnsupportedDeepLLanguageError(
            f"DeepL does not support translation into {name} ('{normalized}'). "
            f"Use engine 'llm' or 'adaptive' for this language."
        )

    config = get_deepl_config()
    if normalized == "en":
        return config.en_variant
    if normalized == "pt":
        return config.pt_variant
    return normalized.upper()
