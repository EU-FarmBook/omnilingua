from __future__ import annotations

from pathlib import Path

from app.pipeline.translate_text_segments import SegmentTranslationStats, translate_segments


def _decode_text_bytes(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _split_text_segments(text: str) -> list[str]:
    segments: list[str] = []
    buffer: list[str] = []

    for line in text.splitlines(keepends=True):
        if line.strip():
            buffer.append(line)
            continue
        if buffer:
            segments.append("".join(buffer))
            buffer = []
        segments.append(line)

    if buffer:
        segments.append("".join(buffer))
    return segments if segments else [text]


def translate_txt(
    txt_in: Path,
    txt_out: Path,
    *,
    target_lang: str,
    source_lang: str | None = None,
    engine: str | None = None,
) -> SegmentTranslationStats:
    original_text = _decode_text_bytes(txt_in.read_bytes())
    segments = _split_text_segments(original_text)
    translated_segments, stats = translate_segments(
        segments,
        target_lang=target_lang,
        source_lang=source_lang,
        engine=engine,
    )
    txt_out.parent.mkdir(parents=True, exist_ok=True)
    txt_out.write_text("".join(translated_segments), encoding="utf-8")
    return stats
