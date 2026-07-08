from __future__ import annotations

import re
from dataclasses import dataclass


_TOKEN_PREFIX = "ZXQNT"
_TOKEN_SUFFIX = "QXZ"
_URL_TRAILING_PUNCTUATION = ".,;:!?)]}\"'"
_PROTECTED_TOKEN_RE = re.compile(
    r"\b(?:ZXQNT\s*\d+(?:\s*QXZ)?|OLPRO\w*\s*\d+)\b",
    re.IGNORECASE,
)

_CONTACT_LABEL_WORDS = {
    "author",
    "authors",
    "case",
    "contact",
    "coordinator",
    "email",
    "e-mail",
    "further",
    "information",
    "page",
    "study",
    "web",
    "webpage",
    "website",
}

_PROTECTED_TEXT_RE = re.compile(
    r"(?P<email>[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)"
    r"|(?P<url>https?://[^\s<>()\"']+|www\.[^\s<>()\"']+)"
    r"|(?P<handle>(?<![\w.@])@[A-Za-z0-9_]{2,30}\b)"
)


@dataclass(frozen=True)
class ProtectedText:
    text: str
    replacements: tuple[str, ...]


def protect_nontranslatable_text(text: str) -> ProtectedText:
    """Replace URLs, emails, and social handles with stable translation tokens."""
    replacements: list[str] = []

    def replace(match: re.Match[str]) -> str:
        value = match.group(0)
        suffix = ""
        if match.lastgroup == "url":
            while value and value[-1] in _URL_TRAILING_PUNCTUATION:
                suffix = value[-1] + suffix
                value = value[:-1]

        token = f"{_TOKEN_PREFIX}{len(replacements)}{_TOKEN_SUFFIX}"
        replacements.append(value)
        return f"{token}{suffix}"

    return ProtectedText(
        text=_PROTECTED_TEXT_RE.sub(replace, text),
        replacements=tuple(replacements),
    )


def restore_protected_text(text: str, replacements: tuple[str, ...]) -> str:
    restored = text
    for index, value in enumerate(replacements):
        token_patterns = (
            rf"\b{_TOKEN_PREFIX}\s*{index}(?:\s*{_TOKEN_SUFFIX})?\b",
            # Legacy token support, including model-translated forms such as OLPROTEGIDO0.
            rf"\bOLPRO\w*\s*{index}\b",
        )
        for pattern_text in token_patterns:
            restored = re.sub(pattern_text, value, restored, flags=re.IGNORECASE)
    return restored


def has_unprotected_translatable_text(text: str) -> bool:
    residual = _PROTECTED_TOKEN_RE.sub(" ", text)
    letters = sum(1 for char in residual if char.isalpha())
    return letters >= 2


def is_contact_identity_text(text: str) -> bool:
    """Return true for contact/name blocks that should be preserved as-is."""
    if not _PROTECTED_TOKEN_RE.search(text):
        return False

    residual = _PROTECTED_TOKEN_RE.sub(" ", text)
    words = re.findall(r"[^\W\d_]+(?:[-'][^\W\d_]+)?", residual, flags=re.UNICODE)
    if len(words) <= 1 or len(words) > 8:
        return False

    informative_words = [word for word in words if word.lower() not in _CONTACT_LABEL_WORDS]
    if not informative_words:
        return True

    return all(word[:1].isupper() for word in informative_words)

def contains_protected_token(text: str) -> bool:
    return bool(_PROTECTED_TOKEN_RE.search(text))

