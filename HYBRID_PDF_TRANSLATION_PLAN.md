# Hybrid PDF Translation Plan

## Goal

Build a hybrid PDF translation pipeline that keeps the current `direct` engine stable while adding safer support for:

- better layout preservation on difficult PDFs such as research papers
- text embedded inside images
- future routing between native-text and vision-assisted paths

The intended model split remains:

- `Qwen3 30B A3B`: translation, language detection, OCR cleanup
- `InternVL`: image-text extraction from cropped regions

## Current State

### What is already implemented

- Shared extracted-block schema in `app/pipeline/block_schema.py`
- Reusable native extraction in `app/pipeline/extract_native_blocks.py`
- Centralized text/vision model config in `app/core/model_config.py`
- Centralized font fallback in `app/pipeline/fonts.py`
- Direct engine refactor to use reusable extracted blocks
- Column-aware ordering for likely two-column pages
- Conservative scholarly block classification:
  - `title`
  - `abstract`
  - `keywords`
  - `caption`
  - `reference`
  - `table`
- Experimental direct-mode image-text translation:
  - cropped embedded image regions
  - `InternVL` extraction
  - `Qwen` translation
  - overlay back onto the PDF
- Standard endpoint cleanup:
  - `/translate/pdf` always uses `direct`
  - `html` remains only under `/translate/pdf/advanced`
- Unit tests and regression harness:
  - `tests/`
  - `run_tests.sh`
  - `run_regression_tests.sh`

### What was tried and rolled back

- Automatic image-text overlays in the `html` engine

That path was removed from normal runtime because `pdftohtml` produces page-background images, not clean isolated figure regions. Overlaying translated labels onto those page backgrounds degraded layout badly and made runtime unacceptably slow.

So at this point:

- `direct` is the recommended production path
- `html` is advanced/fallback/debugging only
- image-text translation should be developed on top of `direct`, not the current `html` page-background flow

## Target Architecture

Use a hybrid direct-first architecture:

1. `native-text lane`
Translate extractable PDF text using the current direct pipeline.

2. `image-text lane`
For embedded image regions only, crop those regions, run `InternVL`, translate labels with `Qwen`, and overlay the results back into the PDF.

3. `future routing lane`
Later, add a document/page router that decides when to use native extraction only and when to augment it with image-region processing.

This keeps the stable path stable and limits vision usage to places where it is actually needed.

## Implemented Modules

### Added

- `app/core/languages.py`
- `app/core/model_config.py`
- `app/pipeline/block_schema.py`
- `app/pipeline/extract_native_blocks.py`
- `app/pipeline/fonts.py`
- `app/pipeline/playwright_support.py`
- `app/pipeline/vision_llm.py`
- `app/pipeline/translate_pdf_image_text.py`
- `tests/run_regression_suite.py`

### Existing modules substantially changed

- `app/pipeline/translate_pdf_direct.py`
- `app/pipeline/translator_llm.py`
- `app/services/pdf_translate_service.py`
- `app/api/routes/translate.py`
- `cli.py`

## Current Gaps

The project still does not solve these well enough:

- true table reconstruction
- span-level scholarly typography preservation
- superscripts/subscripts and formula fidelity
- robust link/annotation preservation in direct mode
- safe automatic routing between text-only and vision-assisted paths
- reliable image-text quality scoring

## Next Safe Milestones

### 1. Protect scholarly layouts further

Focus:

- stop treating references, captions, and table-like rows as generic prose
- add stricter fitting thresholds for protected scholarly blocks
- reduce over-aggressive shrinkage in narrow scientific layouts

Why next:

- research-paper failures are mostly layout-structure problems, not model problems

### 2. Improve direct image-text translation quality

Focus:

- better filtering of embedded image regions
- better OCR/vision block filtering
- fewer noisy overlays
- optional per-case enablement in regression runs

Why next:

- the experimental image-text lane exists, but it needs precision before it can be trusted broadly

### 3. Add annotation/link preservation

Focus:

- preserve real PDF annotations independently from text rewriting
- restore link boxes after direct rewriting

Why next:

- this is a user-visible correctness problem and does not require a redesign

### 4. Add real routing later

Focus:

- `layout_engine=auto`
- page/document classification
- selective vision augmentation

Why later:

- routing before stronger native and image-region behavior would just automate weak decisions

## Design Rules Going Forward

- Do not reintroduce automatic image-text handling into normal `html` mode.
- Keep experimental features opt-in until they pass regression checks.
- Prefer region-based vision processing over page-wide raster processing.
- Keep root shell wrappers as convenience entrypoints, but keep real test logic under `tests/`.
- Do not chase a fake “layout agnostic” promise. Instead, improve robustness by document class and block type.

## Recommended Product Positioning

- `/translate/pdf`: standard path, always `direct`
- `/translate/pdf/advanced`: engine selection, mapping mode, experimental options
- `direct`: recommended
- `html`: advanced/fallback only

## Summary

The repo is no longer at the “just a plan” stage. It already has:

- reusable native extraction
- safer config and validation
- direct-mode structure improvements
- experimental direct-mode image-text translation
- regression automation

The next work should be about quality hardening, not broadening the architecture too early.
