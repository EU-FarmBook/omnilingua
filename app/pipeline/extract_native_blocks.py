from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

import fitz  # PyMuPDF

from app.pipeline.block_schema import ExtractedTextBlock, TextStyleHint


# A list/bullet marker followed by any whitespace — crucially including a TAB,
# which these poster PDFs use for the indent (e.g. "•\t Estonia ..."). Matching
# only "• " (space) misread tab-indented bullets as table rows and blocked the
# first line of a bullet from merging with its continuation.
_BULLET_MARKER_RE = re.compile(r"^\s*[-•▪◦‣·*]\s")


def _starts_with_bullet(text: str) -> bool:
    return bool(_BULLET_MARKER_RE.match(text))


def _strip_leading_bullet(text: str) -> str:
    return _BULLET_MARKER_RE.sub("", text, count=1)


def is_translatable_native_text(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 2:
        return False

    letters = sum(1 for c in stripped if c.isalpha())
    if letters < 2:
        return False

    digits = sum(1 for c in stripped if c.isdigit())
    if digits > 0 and letters <= digits:
        return False

    return True


def _int_color_to_rgb(color: int) -> tuple[float, float, float]:
    r = ((color >> 16) & 255) / 255.0
    g = ((color >> 8) & 255) / 255.0
    b = (color & 255) / 255.0
    return (r, g, b)


def _style_span_for_line(spans: list[dict]) -> dict:
    return max(
        spans,
        key=lambda span: (
            len(str(span.get("text", "")).strip()),
            float(span.get("size", 0) or 0),
        ),
    )


def _merge_bbox(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    return (
        min(left[0], right[0]),
        min(left[1], right[1]),
        max(left[2], right[2]),
        max(left[3], right[3]),
    )


def _line_rotation(direction: object) -> int:
    """Map a PyMuPDF line ``dir`` vector to an ``insert_textbox`` rotate value."""
    try:
        dx, dy = float(direction[0]), float(direction[1])  # type: ignore[index]
    except (TypeError, IndexError, ValueError):
        return 0
    if dx <= -0.92:
        return 180
    if dy <= -0.92:
        return 90
    if dy >= 0.92:
        return 270
    return 0


# Same-row stitching: two fragments belong to one visual row when their boxes
# overlap vertically by at least this fraction of the smaller height. Stacked
# lines with tight leading overlap far less (~40% at worst), so 0.6 separates
# the two cases cleanly.
_ROW_OVERLAP_MIN_RATIO = 0.6
# Widest inter-word gap that still reads as one justified line. Measured
# justified gaps in real factsheets reach ~2.4 em; genuine table-column gaps
# sit well above 3 em.
_ROW_JOIN_MAX_GAP_EMS = 3.0


def _line_fragment(raw_line: dict) -> dict | None:
    """Normalize a raw PyMuPDF line into a fragment record, or None if unusable."""
    spans = raw_line.get("spans", [])
    if not spans:
        return None
    bbox_raw = raw_line.get("bbox")
    if not bbox_raw or len(bbox_raw) != 4:
        return None
    return {
        "bbox": tuple(float(v) for v in bbox_raw),
        "text": "".join(str(span.get("text", "")) for span in spans).strip(),
        "spans": list(spans),
        "rotation": _line_rotation(raw_line.get("dir", (1.0, 0.0))),
    }


def _vertical_overlap_ratio(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    overlap = min(a[3], b[3]) - max(a[1], b[1])
    height_a = a[3] - a[1]
    height_b = b[3] - b[1]
    if overlap <= 0 or height_a <= 0 or height_b <= 0:
        return 0.0
    return overlap / min(height_a, height_b)


def _fragment_font_size(fragment: dict) -> float:
    sizes = [float(span.get("size", 0) or 0) for span in fragment["spans"]]
    return max(sizes) if sizes and max(sizes) > 0 else 11.0


def _stitch_row(fragments: List[dict]) -> List[dict]:
    """Stitch one visual row of fragments back into a single logical line.

    Returns the fragments unchanged when the row does not look like one
    justified line: overlapping fragments (stacked decorations), gaps beyond
    ``_ROW_JOIN_MAX_GAP_EMS`` (table columns), or strongly mismatched font
    sizes (drop caps) all leave the row untouched.
    """
    if len(fragments) < 2:
        return fragments
    ordered = sorted(fragments, key=lambda fragment: fragment["bbox"][0])
    for left, right in zip(ordered, ordered[1:]):
        gap = right["bbox"][0] - left["bbox"][2]
        left_size = _fragment_font_size(left)
        right_size = _fragment_font_size(right)
        if gap < -1.0:
            return fragments
        if gap > _ROW_JOIN_MAX_GAP_EMS * max(left_size, right_size, 1.0):
            return fragments
        if abs(left_size - right_size) > 0.25 * max(left_size, right_size):
            return fragments

    bbox = ordered[0]["bbox"]
    spans: List[dict] = []
    for fragment in ordered:
        bbox = _merge_bbox(bbox, fragment["bbox"])
        spans.extend(fragment["spans"])
    return [
        {
            "bbox": bbox,
            "text": " ".join(fragment["text"] for fragment in ordered if fragment["text"]),
            "spans": spans,
            "rotation": 0,
        }
    ]


def _block_logical_lines(raw_block: dict) -> List[dict]:
    """Return a raw block's lines with same-row word fragments stitched together.

    Fully justified text stretches inter-word gaps; past PyMuPDF's internal
    line-joining threshold every word of such a line arrives as a separate
    "line" sharing one visual row. Left alone, each word becomes its own
    block and is translated in isolation — producing word-for-word output
    with function words stranded in the source language. Fragments sharing a
    row inside one raw block are stitched back into a single logical line
    (x-ordered, space-joined). Digit-only fragments (figures, prices) are
    stitched too, so the sentence keeps its numbers; whether the resulting
    line is translatable is decided afterwards, on the joined text.
    """
    stitched: List[dict] = []
    horizontal: List[dict] = []
    for raw_line in raw_block.get("lines", []):
        fragment = _line_fragment(raw_line)
        if fragment is None or not fragment["text"]:
            continue
        if fragment["rotation"] != 0:
            stitched.append(fragment)
            continue
        horizontal.append(fragment)

    rows: List[List[dict]] = []
    for fragment in horizontal:
        for row in rows:
            if _vertical_overlap_ratio(row[0]["bbox"], fragment["bbox"]) >= _ROW_OVERLAP_MIN_RATIO:
                row.append(fragment)
                break
        else:
            rows.append([fragment])
    for row in rows:
        stitched.extend(_stitch_row(row))
    return stitched


def _can_merge_lines(
    previous: ExtractedTextBlock,
    current: ExtractedTextBlock,
    *,
    multi_column: bool,
) -> bool:
    if previous.page_index != current.page_index:
        return False
    if previous.rotation != current.rotation or previous.rotation != 0:
        return False
    if previous.style.font_name != current.style.font_name:
        return False
    if previous.raw_block_id != current.raw_block_id:
        return False

    font_delta = abs(previous.style.font_size - current.style.font_size)
    if font_delta > max(0.75, previous.style.font_size * 0.08):
        return False

    prev_bbox = previous.bbox
    curr_bbox = current.bbox
    vertical_gap = curr_bbox[1] - prev_bbox[3]
    max_gap = max(previous.style.font_size * 0.7, 4.0)
    # Consecutive lines of a paragraph routinely have slightly overlapping
    # bounding boxes: PyMuPDF line bboxes span the full ascender-to-descender
    # height, which exceeds the baseline-to-baseline pitch, so ``vertical_gap``
    # is mildly negative for normal leading. Tolerate up to ~half a line of
    # overlap; a near-full-height overlap still signals same-row spans and is
    # rejected. (A flat -1.5pt floor wrongly split every body line on tightly
    # leaded layouts, forcing line-by-line translation and ransom-note sizing.)
    min_gap = -max(2.0, previous.style.font_size * 0.55)
    if vertical_gap < min_gap or vertical_gap > max_gap:
        return False

    left_delta = abs(curr_bbox[0] - prev_bbox[0])
    if left_delta > max(previous.style.font_size * 1.5, 18.0):
        return False

    prev_width = prev_bbox[2] - prev_bbox[0]
    curr_width = curr_bbox[2] - curr_bbox[0]
    if prev_width <= 0 or curr_width <= 0:
        return False

    horizontal_overlap = min(prev_bbox[2], curr_bbox[2]) - max(prev_bbox[0], curr_bbox[0])
    if horizontal_overlap < min(prev_width, curr_width) * 0.35:
        return False

    if previous.text.rstrip().endswith(":"):
        return False
    if _looks_like_table_row(previous.text) or _looks_like_table_row(current.text):
        return False
    if _looks_like_reference_line(previous.text) or _looks_like_reference_line(current.text):
        return False
    if _starts_new_structural_block(current.text):
        return False
    if _looks_like_header_or_footer(previous.text) or _looks_like_header_or_footer(current.text):
        return False
    if _is_sentence_boundary(previous.text, current.text) and vertical_gap > max(1.5, previous.style.font_size * 0.18):
        return False

    if multi_column and previous.column_index != current.column_index:
        return False

    return True


def _join_text(previous_text: str, current_text: str) -> str:
    previous_text = previous_text.rstrip()
    current_text = current_text.lstrip()
    if not previous_text:
        return current_text
    if not current_text:
        return previous_text
    if previous_text.endswith("-"):
        return previous_text[:-1] + current_text
    return f"{previous_text} {current_text}"


def _classify_block_kind(text: str, line_count: int) -> str:
    stripped = text.strip()
    if _starts_with_bullet(text):
        return "bullet"
    if stripped.endswith(":") and line_count == 1:
        return "label"
    if line_count > 1:
        return "paragraph"
    return "line"


def _looks_like_table_row(text: str) -> bool:
    # A leading bullet marker uses a tab as its indent; that tab does not make
    # the line a table row, so ignore the marker before inspecting for tabs.
    body = _strip_leading_bullet(text)
    stripped = " ".join(body.split()).strip()
    if not stripped:
        return False
    if "\t" in body:
        return True
    if re.search(r"\b\d+(?:\.\d+)?\s*(?:mg|kg|mL|m2|m²|%)\b", stripped):
        return True
    separators = stripped.count("  ")
    numeric_tokens = len(re.findall(r"\b\d+(?:[.,]\d+)?\b", stripped))
    return separators >= 2 and numeric_tokens >= 2


def _looks_like_reference_line(text: str) -> bool:
    stripped = " ".join(text.split()).strip()
    if not stripped:
        return False
    if re.match(r"^\[\d+\]", stripped):
        return True
    if re.match(r"^\d+\.\s+[A-Z]", stripped):
        return True
    if re.search(r"\(\d{4}[a-z]?\)", stripped) and re.search(r"\bhttps?://|\bdoi[:\s]", stripped.lower()):
        return True
    return False


_REFERENCE_HEADING_RE = re.compile(
    r"^(references|bibliography|literature(?:\s+cited)?|works\s+cited)\s*:?\s*$",
    re.IGNORECASE,
)


def _is_reference_heading(text: str) -> bool:
    return bool(_REFERENCE_HEADING_RE.match(" ".join(text.split()).strip()))


def _mark_reference_section(blocks: List[ExtractedTextBlock]) -> List[ExtractedTextBlock]:
    """Reclassify every block after a standalone References heading.

    A bibliography spans many blocks in varied citation styles that no single
    per-line pattern catches reliably, and translating citations breaks lookups.
    References are conventionally the final section, so once a standalone
    "References"/"Bibliography" heading appears in reading order, mark it and all
    following blocks as ``reference`` (which the translator skips). Guarded to
    the document's latter half so an inline "References:" mention early in the
    body cannot suppress the whole document.
    """
    heading_index: int | None = None
    for index, block in enumerate(blocks):
        if _is_reference_heading(block.text) and index >= len(blocks) // 2:
            heading_index = index
            break
    if heading_index is None:
        return blocks

    result = list(blocks)
    for index in range(heading_index, len(result)):
        block = result[index]
        if block.kind == "reference":
            continue
        result[index] = ExtractedTextBlock(
            block_id=block.block_id,
            page_index=block.page_index,
            bbox=block.bbox,
            text=block.text,
            source=block.source,
            kind="reference",
            confidence=block.confidence,
            style=block.style,
            raw_block_id=block.raw_block_id,
            column_index=block.column_index,
            line_count=block.line_count,
            alignment=block.alignment,
            rotation=block.rotation,
        )
    return result


def _starts_new_structural_block(text: str) -> bool:
    stripped = text.lstrip()
    if not stripped:
        return False
    if _starts_with_bullet(stripped):
        return True
    if re.match(r"^(figure|fig\.|table|abstract|keywords|references)\b", stripped, re.IGNORECASE):
        return True
    if re.match(r"^\d+(?:\.\d+)*\s+[A-Z]", stripped):
        return True
    return False


def _is_sentence_boundary(previous_text: str, current_text: str) -> bool:
    prev = previous_text.rstrip()
    curr = current_text.lstrip()
    if not prev or not curr:
        return False
    if prev.endswith((".", "!", "?")) and curr[:1].isupper():
        return True
    if prev.endswith(";") and curr[:1].isupper():
        return True
    return False


def _looks_like_header_or_footer(text: str) -> bool:
    stripped = " ".join(text.split()).strip()
    if not stripped:
        return False
    lower = stripped.lower()
    if len(stripped) <= 18 and re.search(r"\bpage\s+\d+\b", lower):
        return True
    if re.fullmatch(r"\d+", stripped):
        return True
    if re.search(r"\bdoi[:\s]", lower) or stripped.startswith("http"):
        return True
    return False


def _classify_scholarly_kind(
    text: str,
    line_count: int,
    *,
    page_top: float,
    font_size: float,
    page_width: float,
    block_width: float,
) -> str | None:
    stripped = " ".join(text.split()).strip()
    if not stripped:
        return None

    lower = stripped.lower()

    if _looks_like_table_row(stripped):
        return "table"
    if lower.startswith("abstract") or lower == "abstract":
        return "abstract"
    if lower.startswith("keywords") or lower.startswith("keyword"):
        return "keywords"
    if lower.startswith("references") or lower == "references":
        return "reference"
    if lower.startswith("fig.") or lower.startswith("figure ") or lower.startswith("table "):
        return "caption"
    poster_title_band_bottom = max(120.0, page_width * 0.18)
    if block_width >= page_width * 0.45 and (
        (page_top < 120 and font_size >= 14)
        or (page_top < poster_title_band_bottom and font_size >= 36)
    ):
        return "title"

    if line_count > 1:
        return "paragraph"
    return None


def _resolved_block_kind(
    text: str,
    line_count: int,
    *,
    page_top: float,
    font_size: float,
    page_width: float,
    block_width: float,
) -> str:
    scholarly = _classify_scholarly_kind(
        text,
        line_count,
        page_top=page_top,
        font_size=font_size,
        page_width=page_width,
        block_width=block_width,
    )
    if scholarly is not None:
        return scholarly
    return _classify_block_kind(text, line_count)


def _is_wide_block(block: ExtractedTextBlock, page_width: float) -> bool:
    return (block.bbox[2] - block.bbox[0]) >= page_width * 0.6


def _is_header_band_block(block: ExtractedTextBlock, page_width: float) -> bool:
    block_width = block.bbox[2] - block.bbox[0]
    header_bottom = max(120.0, page_width * 0.28)
    return block.bbox[1] < header_bottom and block_width >= page_width * 0.4


def _detect_multicolumn_page(page_lines: List[ExtractedTextBlock], page_width: float) -> bool:
    if len(page_lines) < 16:
        return False

    narrow = [block for block in page_lines if not _is_wide_block(block, page_width)]
    if len(narrow) < 12:
        return False

    midpoint = page_width / 2.0
    left = [block for block in narrow if ((block.bbox[0] + block.bbox[2]) / 2.0) < midpoint]
    right = [block for block in narrow if ((block.bbox[0] + block.bbox[2]) / 2.0) >= midpoint]
    if len(left) < 5 or len(right) < 5:
        return False

    avg_width = sum((block.bbox[2] - block.bbox[0]) for block in narrow) / max(1, len(narrow))
    return avg_width <= page_width * 0.42


def _with_column_metadata(
    page_lines: List[ExtractedTextBlock],
    page_width: float,
    *,
    multi_column: bool,
) -> List[ExtractedTextBlock]:
    if not multi_column:
        return page_lines

    midpoint = page_width / 2.0
    result: List[ExtractedTextBlock] = []
    for block in page_lines:
        if _is_wide_block(block, page_width) or _is_header_band_block(block, page_width):
            result.append(block)
            continue
        center_x = (block.bbox[0] + block.bbox[2]) / 2.0
        column_index = 0 if center_x < midpoint else 1
        result.append(
            ExtractedTextBlock(
                block_id=block.block_id,
                page_index=block.page_index,
                bbox=block.bbox,
                text=block.text,
                source=block.source,
                kind=block.kind,
                confidence=block.confidence,
                style=block.style,
                raw_block_id=block.raw_block_id,
                column_index=column_index,
                line_count=block.line_count,
                alignment=block.alignment,
                rotation=block.rotation,
            )
        )
    return result


def _sort_page_lines(
    page_lines: List[ExtractedTextBlock],
    page_width: float,
    *,
    multi_column: bool,
) -> List[ExtractedTextBlock]:
    if not multi_column:
        return sorted(page_lines, key=lambda block: (round(block.bbox[1], 1), round(block.bbox[0], 1)))

    narrow = [block for block in page_lines if block.column_index is not None]
    if not narrow:
        return sorted(page_lines, key=lambda block: (round(block.bbox[1], 1), round(block.bbox[0], 1)))

    first_column_top = min(block.bbox[1] for block in narrow)
    last_column_bottom = max(block.bbox[3] for block in narrow)
    full_width_top = [
        block for block in page_lines if block.column_index is None and block.bbox[1] < first_column_top - 6
    ]
    full_width_middle = [
        block
        for block in page_lines
        if block.column_index is None and not (block.bbox[1] < first_column_top - 6 or block.bbox[1] > last_column_bottom + 6)
    ]
    full_width_bottom = [
        block for block in page_lines if block.column_index is None and block.bbox[1] > last_column_bottom + 6
    ]
    left_column = [block for block in page_lines if block.column_index == 0]
    right_column = [block for block in page_lines if block.column_index == 1]

    ordered: List[ExtractedTextBlock] = []
    for group in (full_width_top, left_column, right_column, full_width_middle, full_width_bottom):
        ordered.extend(sorted(group, key=lambda block: (round(block.bbox[1], 1), round(block.bbox[0], 1))))
    return ordered


def _detect_line_alignment(
    line_bboxes: List[tuple[float, float, float, float]],
    text: str = "",
) -> str:
    """Infer whether a block's source lines were centered or right-aligned.

    Centered lines share a common midpoint while both edges wander; right-aligned
    lines share a common right edge while their left edges wander; left-aligned
    (and justified) lines share a common left edge. Only report "center"/"right"
    on clear geometric evidence from at least two lines — a single line carries
    none, so it stays "left" (the safe default) and the translation is anchored
    on the source's left edge.
    """
    if len(line_bboxes) < 2:
        return "left"
    lefts = [bbox[0] for bbox in line_bboxes]
    rights = [bbox[2] for bbox in line_bboxes]
    centers = [(bbox[0] + bbox[2]) / 2.0 for bbox in line_bboxes]
    left_spread = max(lefts) - min(lefts)
    right_spread = max(rights) - min(rights)
    center_spread = max(centers) - min(centers)
    if left_spread > 6.0 and center_spread <= max(3.0, left_spread * 0.25):
        return "center"
    # Right-aligned: right edges lock together while the left edge stays ragged
    # across *every* line. Justified paragraphs and hanging-indent bullets also
    # line their right edges up, but their left edges are clustered on a common
    # indent — only the marker/first line sits further left as the lone outlier.
    # Dropping that single most-extreme (smallest) left therefore collapses their
    # spread to ~0, whereas genuinely right-aligned lines keep a wide spread.
    # Require ≥3 lines (2 lines cannot tell the two apart) and exclude bullets.
    if (
        len(lefts) >= 3
        and right_spread <= 2.5
        and left_spread > 6.0
        and center_spread > right_spread
        and not _starts_with_bullet(text)
    ):
        inner = sorted(lefts)[1:]
        if (max(inner) - min(inner)) > 4.0:
            return "right"
    return "left"


def _group_page_lines(
    page_lines: List[ExtractedTextBlock],
    next_block_id: int,
    *,
    multi_column: bool,
    page_width: float,
) -> tuple[List[ExtractedTextBlock], int]:
    grouped: List[ExtractedTextBlock] = []
    current: ExtractedTextBlock | None = None
    current_line_count = 0
    current_line_bboxes: List[tuple[float, float, float, float]] = []

    def flush() -> None:
        nonlocal current, current_line_count, next_block_id
        if current is None:
            return
        kind = _resolved_block_kind(
            current.text,
            current_line_count,
            page_top=current.bbox[1],
            font_size=current.style.font_size,
            page_width=page_width,
            block_width=current.bbox[2] - current.bbox[0],
        )
        alignment = _detect_line_alignment(current_line_bboxes, current.text)
        # Figure/table captions are conventionally centered under their figure;
        # a single line carries no geometric evidence either way, so preserve
        # the visual midpoint instead of anchoring the translation left.
        if kind == "caption" and current_line_count == 1:
            alignment = "center"
        grouped.append(
            ExtractedTextBlock(
                block_id=next_block_id,
                page_index=current.page_index,
                bbox=current.bbox,
                text=current.text,
                source=current.source,
                kind=kind,
                confidence=current.confidence,
                style=current.style,
                raw_block_id=current.raw_block_id,
                column_index=current.column_index,
                line_count=current_line_count,
                alignment=alignment,
                rotation=current.rotation,
            )
        )
        next_block_id += 1
        current = None
        current_line_count = 0
        current_line_bboxes.clear()

    for line in page_lines:
        if current is None:
            current = line
            current_line_count = 1
            current_line_bboxes[:] = [line.bbox]
            continue
        if _can_merge_lines(current, line, multi_column=multi_column):
            current = ExtractedTextBlock(
                block_id=current.block_id,
                page_index=current.page_index,
                bbox=_merge_bbox(current.bbox, line.bbox),
                text=_join_text(current.text, line.text),
                source=current.source,
                kind="paragraph",
                confidence=min(current.confidence, line.confidence),
                style=current.style,
                raw_block_id=current.raw_block_id,
                column_index=current.column_index,
                line_count=current.line_count + line.line_count,
                rotation=current.rotation,
            )
            current_line_count += 1
            current_line_bboxes.append(line.bbox)
            continue
        flush()
        current = line
        current_line_count = 1
        current_line_bboxes[:] = [line.bbox]

    flush()
    return (grouped, next_block_id)


def _ends_with_word_hyphen(text: str) -> bool:
    stripped = text.rstrip()
    return len(stripped) >= 2 and stripped.endswith("-") and stripped[-2].isalpha()


def _merge_hyphen_continuations(
    page_blocks: List[ExtractedTextBlock],
    *,
    page_width: float,
) -> List[ExtractedTextBlock]:
    """Merge blocks split mid-word by a trailing line-break hyphen.

    ``_can_merge_lines`` refuses to merge across raw PyMuPDF blocks or font
    changes (e.g. a bold bullet lead-in), so a hyphenated line break at such a
    boundary strands the word fragments in separate blocks and each half gets
    translated on its own ("bioecono-" / "my. …"). Reading order is already
    resolved here, so a block ending in a word hyphen whose successor starts
    lowercase and sits directly below it is a safe continuation.
    """
    merged: List[ExtractedTextBlock] = []
    for block in page_blocks:
        previous = merged[-1] if merged else None
        if previous is not None and _ends_with_word_hyphen(previous.text):
            current_text = block.text.lstrip()
            font_size = previous.style.font_size
            vertical_gap = block.bbox[1] - previous.bbox[3]
            same_column = previous.column_index == block.column_index
            if (
                previous.page_index == block.page_index
                and same_column
                and previous.rotation == 0 == block.rotation
                and current_text[:1].islower()
                and -max(2.0, font_size * 0.55) <= vertical_gap <= max(font_size * 0.7, 4.0)
            ):
                bbox = _merge_bbox(previous.bbox, block.bbox)
                text = _join_text(previous.text, block.text)
                line_count = previous.line_count + block.line_count
                merged[-1] = ExtractedTextBlock(
                    block_id=previous.block_id,
                    page_index=previous.page_index,
                    bbox=bbox,
                    text=text,
                    source=previous.source,
                    kind=_resolved_block_kind(
                        text,
                        line_count,
                        page_top=bbox[1],
                        font_size=font_size,
                        page_width=page_width,
                        block_width=bbox[2] - bbox[0],
                    ),
                    confidence=min(previous.confidence, block.confidence),
                    style=previous.style,
                    raw_block_id=previous.raw_block_id,
                    column_index=previous.column_index,
                    line_count=line_count,
                    alignment=previous.alignment,
                )
                continue
        merged.append(block)
    return merged


def extract_native_text_blocks(pdf_path: Path) -> List[ExtractedTextBlock]:
    doc = fitz.open(str(pdf_path))
    page_line_blocks: List[ExtractedTextBlock] = []
    grouped_blocks: List[ExtractedTextBlock] = []
    line_id = 0
    grouped_id = 0

    try:
        for page_index, page in enumerate(doc):
            page_line_blocks.clear()
            text_dict = page.get_text("dict")
            for raw_block_index, raw_block in enumerate(text_dict.get("blocks", [])):
                if raw_block.get("type", 0) != 0:
                    continue

                for line in _block_logical_lines(raw_block):
                    text = line["text"]
                    if not is_translatable_native_text(text):
                        continue

                    style_span = _style_span_for_line(line["spans"])
                    font_name = str(style_span.get("font", "helv"))
                    font_size = float(style_span.get("size", 11.0))
                    color_rgb = _int_color_to_rgb(int(style_span.get("color", 0)))

                    page_line_blocks.append(
                        ExtractedTextBlock(
                            block_id=line_id,
                            page_index=page_index,
                            bbox=line["bbox"],
                            text=text,
                            source="native",
                            kind="line",
                            confidence=1.0,
                            style=TextStyleHint(
                                font_name=font_name,
                                font_size=font_size if font_size > 0 else 11.0,
                                color_rgb=color_rgb,
                            ),
                            raw_block_id=raw_block_index,
                            line_count=1,
                            rotation=line["rotation"],
                        )
                    )
                    line_id += 1

            page_width = float(page.rect.width)
            multi_column = _detect_multicolumn_page(page_line_blocks, page_width)
            page_line_blocks_with_columns = _with_column_metadata(
                page_line_blocks,
                page_width,
                multi_column=multi_column,
            )
            ordered_lines = _sort_page_lines(
                page_line_blocks_with_columns,
                page_width,
                multi_column=multi_column,
            )
            page_grouped, grouped_id = _group_page_lines(
                ordered_lines,
                grouped_id,
                multi_column=multi_column,
                page_width=page_width,
            )
            page_grouped = _merge_hyphen_continuations(page_grouped, page_width=page_width)
            grouped_blocks.extend(page_grouped)

        return _mark_reference_section(grouped_blocks)
    finally:
        doc.close()


def collect_untranslatable_line_rects(pdf_path: Path) -> dict[int, List[tuple[float, float, float, float]]]:
    """Return, per page index, the bboxes of native text lines that are never
    translated (filtered by :func:`is_translatable_native_text`).

    These number/symbol-only lines never enter a block, so they are never
    intentionally redacted. When a translated block's bounding box vertically
    bleeds into such a line's row (common for parenthetical figures under a
    bullet), the block's redaction would otherwise erase them — the "numbers in
    parenthesis disappeared" failure. Callers feed these rects into the
    redaction-avoidance set so the source figures survive.
    """
    doc = fitz.open(str(pdf_path))
    rects: dict[int, List[tuple[float, float, float, float]]] = {}
    try:
        for page_index, page in enumerate(doc):
            for raw_block in page.get_text("dict").get("blocks", []):
                if raw_block.get("type", 0) != 0:
                    continue
                # Uses the same row-stitched view as extract_native_text_blocks:
                # a digit-only fragment absorbed into a translated line must NOT
                # be preserved separately, or its source glyphs would survive
                # underneath the re-rendered translation.
                for line in _block_logical_lines(raw_block):
                    if is_translatable_native_text(line["text"]):
                        continue
                    rects.setdefault(page_index, []).append(line["bbox"])
    finally:
        doc.close()
    return rects


def collect_language_detection_samples(
    blocks: List[ExtractedTextBlock],
    *,
    min_length: int = 24,
    limit: int = 18,
) -> List[str]:
    candidates: List[str] = []
    aggregated: List[str] = []
    buffer: List[str] = []
    buffer_chars = 0

    for block in blocks:
        text = " ".join(block.text.split()).strip()
        if len(text) < min_length:
            continue
        if _should_skip_detection_text(block, text):
            continue
        candidates.append(text)
        buffer.append(text)
        buffer_chars += len(text)
        if buffer_chars >= 320:
            aggregated.append(" ".join(buffer))
            buffer = []
            buffer_chars = 0
        if len(candidates) >= limit * 2:
            break

    if buffer:
        aggregated.append(" ".join(buffer))

    if aggregated:
        return aggregated[:limit]
    if candidates:
        return candidates[:limit]

    fallback: List[str] = []
    for block in blocks[:limit]:
        text = " ".join(block.text.split()).strip()
        if text:
            fallback.append(text)
    return fallback


def _should_skip_detection_text(block: ExtractedTextBlock, text: str) -> bool:
    if text.endswith(":"):
        return True
    if block.kind in {"caption", "reference", "table", "keywords", "label", "bullet"}:
        return True
    if _looks_like_header_or_footer(text):
        return True
    if "@" in text or "http" in text.lower():
        return True
    letters = sum(1 for c in text if c.isalpha())
    digits = sum(1 for c in text if c.isdigit())
    if letters < 12:
        return True
    if digits and digits >= max(3, letters * 0.35):
        return True
    if sum(1 for ch in text if ch.isupper()) >= max(10, int(len(text) * 0.55)):
        return True
    return False


def extract_pdf_metadata_language(pdf_path: Path) -> Optional[str]:
    doc = fitz.open(str(pdf_path))
    try:
        metadata = doc.metadata or {}
        raw_candidates = [
            metadata.get("language"),
            metadata.get("lang"),
            metadata.get("subject"),
            metadata.get("keywords"),
        ]
        for raw in raw_candidates:
            if not raw:
                continue
            match = re.search(r"\b([a-z]{2})(?:[-_][A-Za-z]{2})?\b", str(raw), re.IGNORECASE)
            if match:
                return match.group(1).lower()
        return None
    finally:
        doc.close()
