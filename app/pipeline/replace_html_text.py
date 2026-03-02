# replace_html_text.py

from __future__ import annotations

import json

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from bs4 import BeautifulSoup, NavigableString


@dataclass(frozen=True)
class ReplacementStats:
    replaced: int
    skipped: int


def load_mapping(mapping_json: Path) -> Dict[str, str]:
    """
    Load a JSON mapping: { "original text": "replacement text" }.

    For now this is your placeholder for translation output.
    Later you can generate this mapping using your translation model.
    """
    data = json.loads(mapping_json.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("mapping_json must contain a JSON object/dict.")
    # Ensure keys/values are strings
    out: Dict[str, str] = {}
    for k, v in data.items():
        out[str(k)] = str(v)
    return out


def replace_text_nodes(html_in: Path, html_out: Path, mapping: Dict[str, str]) -> ReplacementStats:
    """
    Replace text nodes in the HTML while leaving the DOM structure and CSS intact.

    IMPORTANT:
    - We only replace *exact* text matches (after strip) to keep behaviour predictable.
    - This is a baseline. For better results, we’ll later replace by element IDs or
      positioned spans rather than raw text matching.

    Returns ReplacementStats for logging.
    """
    soup = BeautifulSoup(html_in.read_text(encoding="utf-8", errors="ignore"), "lxml")

    replaced = 0
    skipped = 0

    for node in soup.find_all(string=True):
        if not isinstance(node, NavigableString):
            continue

        original = str(node)
        stripped = original.strip()
        if not stripped:
            skipped += 1
            continue

        if stripped in mapping:
            new_text = mapping[stripped]

            # Preserve leading/trailing whitespace around the stripped content
            # so we don't accidentally change spacing layout.
            node.replace_with(original.replace(stripped, new_text))
            replaced += 1
        else:
            skipped += 1

    html_out.write_text(str(soup), encoding="utf-8")
    return ReplacementStats(replaced=replaced, skipped=skipped)
