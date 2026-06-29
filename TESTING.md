# Testing

This repo has three useful test levels. Run commands from the repository root.

## Fast Unit Test Suite

Run this as the default quick validation for normal code changes:

```bash
TRANSLATION_ENGINE=llm ./run_tests.sh
```

`TRANSLATION_ENGINE=llm` keeps tests deterministic. Some local shells may default to
`adaptive`, which changes validation expectations in a few tests.

You can also run individual unittest modules directly:

```bash
TRANSLATION_ENGINE=llm .venv/bin/python -m unittest tests.test_api_schema
TRANSLATION_ENGINE=llm .venv/bin/python -m unittest tests.test_document_translate_service
```

## Regression Suite

Use this for broader document-pipeline checks against curated fixtures:

```bash
./run_regression_tests.sh
```

Outputs are written under:

```text
output/regression/
```

Each case stores its stdout, stderr, generated document, and extracted output text.

## Full EU Translation Matrix

Use this when you want to translate every supported file in `input/` into all 24 EU
languages:

```bash
./run_all_eu_translations.sh
```

Outputs are written under:

```text
output/eu_translations/<lang>/
output/eu_translations/_logs/
output/eu_translations/manifest.json
```

The runner prints the resolved translation engine, total run start/finish times,
and per-translation duration. The same timing fields are stored in `manifest.json`.

Useful overrides:

```bash
ENGINE=adaptive ./run_all_eu_translations.sh
OVERWRITE=1 ./run_all_eu_translations.sh
INPUT_DIR=/path/to/input OUTPUT_DIR=/path/to/output ./run_all_eu_translations.sh
```

This is a long-running integration utility, not part of the normal unit test script.

## Supported Formats

The public document pipeline currently supports:

```text
.pdf, .txt, .doc, .docx, .ppt, .pptx
```

Unsupported structured data formats such as `.json`, `.csv`, `.xls`, and `.xlsx`
are intentionally rejected.
