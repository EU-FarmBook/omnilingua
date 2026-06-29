from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

from app.pipeline.translator_factory import get_translator
from app.pipeline.translator_llm import LLMTranslator, should_retry_translation


@dataclass(frozen=True)
class SegmentTranslationStats:
    segments_total: int
    segments_translated: int
    segments_rejected: int
    api_calls: int
    source_lang: str


def detect_source_language_for_segments(
    translator: LLMTranslator,
    segments: Iterable[str],
    *,
    source_lang: Optional[str] = None,
) -> str:
    if source_lang:
        return source_lang

    samples = [text for text in (segment.strip() for segment in segments) if len(text) >= 24][:18]
    return translator.detect_language(samples)


def translate_segments(
    segments: List[str],
    *,
    target_lang: str,
    source_lang: Optional[str] = None,
    engine: Optional[str] = None,
) -> tuple[List[str], SegmentTranslationStats]:
    translator = get_translator(engine)
    resolved_source = detect_source_language_for_segments(
        translator,
        segments,
        source_lang=source_lang,
    )

    if resolved_source == target_lang:
        raise ValueError(f"Source and target language are the same ({resolved_source}).")

    translated: List[str] = list(segments)
    api_calls = 0
    translated_count = 0
    rejected = 0

    text_segments = [(index, text) for index, text in enumerate(segments) if text.strip()]
    if not text_segments:
        return (
            translated,
            SegmentTranslationStats(
                segments_total=len(segments),
                segments_translated=0,
                segments_rejected=0,
                api_calls=0,
                source_lang=resolved_source,
            ),
        )

    batch_size = max(1, min(translator.batch_size, 40))
    for start in range(0, len(text_segments), batch_size):
        batch_items = text_segments[start:start + batch_size]
        batch_texts = [text for _, text in batch_items]
        batch_translations = translator.translate_strings_batch(
            batch_texts,
            source_lang=resolved_source,
            target_lang=target_lang,
        )
        api_calls += 1

        for offset, (segment_index, original_text) in enumerate(batch_items):
            candidate = batch_translations.get(offset)
            if not candidate:
                rejected += 1
                continue

            if should_retry_translation(original_text, candidate, resolved_source, target_lang):
                retry = translator.translate_single_strict(original_text, resolved_source, target_lang)
                api_calls += 1
                if not retry or should_retry_translation(original_text, retry, resolved_source, target_lang):
                    rejected += 1
                    continue
                candidate = retry

            translated[segment_index] = candidate
            translated_count += 1

    return (
        translated,
        SegmentTranslationStats(
            segments_total=len(segments),
            segments_translated=translated_count,
            segments_rejected=rejected,
            api_calls=api_calls,
            source_lang=resolved_source,
        ),
    )
