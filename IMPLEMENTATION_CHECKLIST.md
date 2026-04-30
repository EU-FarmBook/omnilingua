# Implementation Checklist

## Objective

Keep the currently working `direct` path stable while improving:

- scholarly PDF layout preservation
- experimental image-text translation in direct mode
- regression safety

This checklist is updated to match what is already done in the repo.

## Already Completed

- Shared extracted block schema
- Reusable native extraction module
- Centralized language validation for the 24 EU languages
- Standardized text/vision model config
- Centralized font fallback
- Direct-mode extraction refactor
- Multi-column-aware ordering
- Conservative scholarly block classification
- Experimental direct-mode image-text translation
- Standard endpoint simplification:
  - `/translate/pdf` -> `direct` only
  - `/translate/pdf/advanced` -> advanced options
- Unit test suite
- Manifest-driven regression harness

## Current Priority Order

1. Improve scholarly layout fidelity in `direct`
2. Improve experimental image-text translation precision in `direct`
3. Preserve links and annotations
4. Expand regression coverage and quality gates
5. Add routing and `auto` mode only after the above are reliable

## Milestone 1: Scholarly PDF Hardening

Estimated effort: ongoing

- Improve handling of:
  - titles
  - abstracts
  - keywords
  - captions
  - references
  - table-like rows
- Reduce harmful merges on multi-column pages
- Tighten fitting rules for protected scholarly blocks
- Reduce shrink-heavy writeback in narrow scientific layouts

Definition of done:

- better reading order on research papers
- fewer broken titles/abstracts/captions
- fewer obvious cross-column mistakes

## Milestone 2: Direct Image-Text Quality

Estimated effort: ongoing

- Filter embedded image regions better
- Reduce noisy or low-value OCR blocks
- Improve overlay placement and text sizing
- Add per-case opt-in in regression manifests where needed

Definition of done:

- image-text translation is usable on selected PDFs
- overlays do not degrade otherwise good pages

## Milestone 3: Link and Annotation Preservation

Estimated effort: 2 to 4 days

- Preserve PDF annotations independently of text rewriting
- Restore hyperlinks after direct rewrite
- Add regression checks for annotated documents

Definition of done:

- translated PDFs preserve real link annotations

## Milestone 4: Regression Tightening

Estimated effort: 2 to 4 days

- Expand `tests/integration_cases.json`
- Add stronger per-case expectations:
  - language-script presence
  - target-language token hits
  - image-text opt-in cases
- Keep regression outputs isolated under `output/regression/`

Definition of done:

- regressions are easier to catch automatically
- basic translation health is checked on representative PDFs

## Milestone 5: Future Hybrid Routing

Estimated effort: later

- Add document/page classification
- Add `layout_engine=auto`
- Route pages or regions to native or vision-assisted processing

Definition of done:

- routing decisions improve quality rather than just automating current weaknesses

## Immediate Next Tasks

- Retest current research-paper cases with the latest column-aware extraction
- Improve scholarly protected-block handling further if those still fail visibly
- Add at least one regression case with `translate_image_text=true`
- Add annotation-preservation work after layout quality stabilizes

## Current Test Layout

- Test logic and manifests live under `tests/`
- Root shell wrappers exist only as convenience entrypoints:
  - `run_tests.sh`
  - `run_regression_tests.sh`

## Notes

- The `html` engine is still supported, but only as an advanced/fallback path.
- Automatic image-text translation must not be reintroduced into normal HTML mode without a different architecture.
- “Layout agnostic” should be treated as a quality goal, not as a literal guarantee. The practical path is stronger handling by document class and block type.
