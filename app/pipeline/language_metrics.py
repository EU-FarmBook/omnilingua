"""Per-language text-expansion metrics for layout planning.

When English text is translated, it gets longer or shorter by an amount that is
systematic per target language (Romance/Greek expand ~20-30%, Slavic contract or
stay near parity). These factors were measured empirically (DeepL for the 22
supported languages, 16 domain sentences) and cross-checked against the IBM /
W3C localization guidance; see ``docs/text-expansion-study.html``.

The direct PDF engine already measures the *actual* fit of each translated string
locally, so these factors are not used to decide a block's size on their own.
They provide (a) a font-size prior when a block has no siblings to harmonize with
and (b) a starting scale that reduces wasted shrink iterations.
"""
from __future__ import annotations

import math

# Mean character-length ratio (translated / English). Irish is deliberately
# omitted from the measurement (LLM degeneration made its data meaningless); it
# falls back to the neutral default below.
EXPANSION_RATIO: dict[str, float] = {
    "fr": 1.305,
    "es": 1.235,
    "de": 1.225,
    "it": 1.221,
    "pt": 1.210,
    "el": 1.204,
    "bg": 1.161,
    "ro": 1.152,
    "pl": 1.147,
    "hu": 1.138,
    "nl": 1.128,
    "mt": 1.115,
    "fi": 1.077,
    "lt": 1.070,
    "lv": 1.060,
    "et": 1.054,
    "sk": 1.038,
    "da": 1.029,
    "sv": 1.027,
    "sl": 1.001,
    "cs": 0.982,
    "hr": 0.970,
    "en": 1.000,
}

_DEFAULT_RATIO = 1.15  # conservative expansion for anything unmeasured (incl. ga)


def expansion_ratio(target_lang: str) -> float:
    """Mean character-length ratio for English -> ``target_lang``."""
    return EXPANSION_RATIO.get((target_lang or "").strip().lower(), _DEFAULT_RATIO)


def area_font_scale(target_lang: str) -> float:
    """Font-size multiplier for a reflowing paragraph in ``target_lang``.

    A paragraph that reflows fills an area, and characters x fontsize^2 ~ area,
    so to hold L times more text in the same box the font scales by ~1/sqrt(L).
    Capped at 1.0: never *enlarge* text above its source size, only predict how
    far it may need to shrink. Contracting languages therefore get 1.0.
    """
    return min(1.0, 1.0 / math.sqrt(expansion_ratio(target_lang)))
