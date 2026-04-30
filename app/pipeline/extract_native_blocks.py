from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

import fitz  # PyMuPDF

from app.pipeline.block_schema import ExtractedTextBlock, TextStyleHint


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


def _can_merge_lines(
    previous: ExtractedTextBlock,
    current: ExtractedTextBlock,
    *,
    multi_column: bool,
) -> bool:
    if previous.page_index != current.page_index:
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
    if vertical_gap < -1.5 or vertical_gap > max_gap:
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
    if stripped.startswith(("- ", "• ", "▪ ", "* ")):
        return "bullet"
    if stripped.endswith(":") and line_count == 1:
        return "label"
    if line_count > 1:
        return "paragraph"
    return "line"


def _looks_like_table_row(text: str) -> bool:
    stripped = " ".join(text.split()).strip()
    if not stripped:
        return False
    if "\t" in text:
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


def _starts_new_structural_block(text: str) -> bool:
    stripped = text.lstrip()
    if not stripped:
        return False
    if stripped.startswith(("- ", "• ", "▪ ", "* ")):
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
    if page_top < 120 and font_size >= 14 and block_width >= page_width * 0.45:
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
        if _is_wide_block(block, page_width):
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

    def flush() -> None:
        nonlocal current, current_line_count, next_block_id
        if current is None:
            return
        grouped.append(
            ExtractedTextBlock(
                block_id=next_block_id,
                page_index=current.page_index,
                bbox=current.bbox,
                text=current.text,
                source=current.source,
                kind=_resolved_block_kind(
                    current.text,
                    current_line_count,
                    page_top=current.bbox[1],
                    font_size=current.style.font_size,
                    page_width=page_width,
                    block_width=current.bbox[2] - current.bbox[0],
                ),
                confidence=current.confidence,
                style=current.style,
                raw_block_id=current.raw_block_id,
                column_index=current.column_index,
                line_count=current_line_count,
            )
        )
        next_block_id += 1
        current = None
        current_line_count = 0

    for line in page_lines:
        if current is None:
            current = line
            current_line_count = 1
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
            )
            current_line_count += 1
            continue
        flush()
        current = line
        current_line_count = 1

    flush()
    return (grouped, next_block_id)


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

                for raw_line in raw_block.get("lines", []):
                    spans = raw_line.get("spans", [])
                    if not spans:
                        continue

                    text = "".join(str(span.get("text", "")) for span in spans).strip()
                    if not is_translatable_native_text(text):
                        continue

                    bbox_raw = raw_line.get("bbox")
                    if not bbox_raw or len(bbox_raw) != 4:
                        continue

                    first_span = spans[0]
                    font_name = str(first_span.get("font", "helv"))
                    font_size = float(first_span.get("size", 11.0))
                    color_rgb = _int_color_to_rgb(int(first_span.get("color", 0)))

                    page_line_blocks.append(
                        ExtractedTextBlock(
                            block_id=line_id,
                            page_index=page_index,
                            bbox=tuple(float(v) for v in bbox_raw),
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
            grouped_blocks.extend(page_grouped)

        return grouped_blocks
    finally:
        doc.close()


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
