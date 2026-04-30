from __future__ import annotations

from typing import Optional


EU_LANGUAGE_NAMES = {
    "bg": "Bulgarian",
    "cs": "Czech",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "et": "Estonian",
    "fi": "Finnish",
    "fr": "French",
    "ga": "Irish",
    "hr": "Croatian",
    "hu": "Hungarian",
    "it": "Italian",
    "lt": "Lithuanian",
    "lv": "Latvian",
    "mt": "Maltese",
    "nl": "Dutch",
    "pl": "Polish",
    "pt": "Portuguese",
    "ro": "Romanian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "sv": "Swedish",
}

SUPPORTED_EU_LANGUAGE_CODES = frozenset(EU_LANGUAGE_NAMES)


def supported_language_codes_text() -> str:
    return ", ".join(sorted(SUPPORTED_EU_LANGUAGE_CODES))


def normalize_language_code(value: str) -> str:
    code = value.strip().lower().replace("_", "-")
    if len(code) == 5 and code[2] == "-":
        code = code[:2]
    return code


def validate_optional_language_code(value: Optional[str], field_name: str) -> Optional[str]:
    if value is None:
        return None

    code = normalize_language_code(value)
    if len(code) != 2 or not code.isalpha():
        raise ValueError(
            f"{field_name} must be a two-letter ISO 639-1 language code. "
            f"Supported languages: {supported_language_codes_text()}"
        )

    if code not in SUPPORTED_EU_LANGUAGE_CODES:
        raise ValueError(
            f"{field_name} '{code}' is not supported. "
            f"Supported languages: {supported_language_codes_text()}"
        )

    return code
