# OmniLingua

Structure-preserving document translation across the 24 official EU languages (FastAPI + CLI).

Translate born-digital PDFs and selected office/text documents while preserving structure as much as possible.

> **Historical note:** this project started life as "Doc Generator", and the old name still
> appears in a few internals (for example the `doc_generator_api_` temp-dir prefix). The
> service is deployed as **OmniLingua**.

This project supports:
- native document translation for `txt`, `docx`, and `pptx`
- conversion-assisted support for legacy `doc` and `ppt` when LibreOffice/`soffice` is available
- two PDF engines:
  - `direct`: the standard production path
  - `html`: advanced/fallback `PDF -> HTML -> translate/replace -> PDF`
- three translation backends (`llm`, `deepl`, `adaptive`) — see [Translation engines](#translation-engines)

## Documentation

- [TESTING.md](./TESTING.md) — test levels and commands
- [docs/flow-technical.html](./docs/flow-technical.html) — visual end-to-end pipeline walkthrough (open in a browser)
- [docs/omnilingua_qna.html](./docs/omnilingua_qna.html) — internal Q&A / FAQ about how the service works
- [docs/text-expansion-study.html](./docs/text-expansion-study.html) — measured English→24-EU-language text expansion factors, and the sibling-group font harmonization they motivated (with before/after results)

## Features

- CLI workflow for translation and JSON mapping replacement
- FastAPI endpoints for translated PDF/document download
- Selectable translation backend: LLM, DeepL, or adaptive (DeepL with LLM fallback)
- Auto language detection (or manual `--source-lang`)
- Validation for the 24 EU language codes
- Output auto-naming with language suffix when output is a directory
- Direct-mode scholarly layout hardening:
  - reusable block extraction
  - column-aware ordering
  - conservative scholarly block classification
  - stronger glyph fallback
  - sibling-group font harmonization (consistent size for same-role text; preserves source hierarchy)
- Modular app structure (`app/api`, `app/services`, `app/pipeline`)
- Unit and regression test entrypoints

## Requirements

- Python 3.10+
- Poppler tools (`pdftohtml`, `pdftotext`, `pdfinfo`) for `html` engine
- Playwright Chromium for `html` engine
- OpenAI-compatible LLM endpoint
- DeepL API key only for the `deepl` and `adaptive` engines
- LibreOffice/`soffice` only if you want legacy `.doc` or `.ppt` conversion support

Install system deps (Ubuntu/Debian):

```bash
sudo apt-get update
sudo apt-get install -y poppler-utils
```

Install Python deps:

```bash
pip install -r requirements.txt
```

Install Playwright browser:

```bash
playwright install chromium
```

## Environment

Copy sample and fill values:

```bash
cp .env.sample .env
```

Required keys:

```bash
TEXT_MODEL_URL=
TEXT_MODEL_API_KEY=
TEXT_MODEL_NAME=
VISION_MODEL_URL=
VISION_MODEL_API_KEY=
VISION_MODEL_NAME=
DEFAULT_NUM_PREDICT=
COMBINE_NUM_PREDICT=
PER_REQUEST_TIMEOUT=
BASIC_AUTH_USERNAME=
BASIC_AUTH_PASSWORD=

# Translation engine: llm (default) | deepl | adaptive
TRANSLATION_ENGINE=
# Required for the deepl and adaptive engines:
DEEPL_API_KEY=
DEEPL_SERVER_URL=
DEEPL_EN_VARIANT=
DEEPL_PT_VARIANT=
```

Legacy names are still accepted as fallbacks for backward compatibility:

- text model: `TEXT_URL`, `TEXT_API_KEY`, `TEXT_MODEL`, `RUNPOD_VLLM_HOST`, `VLLM_API_KEY`, `VLLM_MODEL`
- vision model: `VISION_URL`, `VISION_API_KEY`, `VISION_MODEL`
- DeepL: `DEEPL_AUTH_KEY` (for `DEEPL_API_KEY`), `DEEPL_API_URL` (for `DEEPL_SERVER_URL`)

## Translation engines

Translation can be performed by one of three engines, selected per request via the
`engine` parameter (API) / `--engine` flag (CLI), or globally via the
`TRANSLATION_ENGINE` env var. When unset, the default is `llm`.

| Engine | Behavior |
| --- | --- |
| `llm` | LLM only (OpenAI-compatible / vLLM endpoint). The original behavior. |
| `deepl` | DeepL only. Errors (quota, rate limit, auth) are surfaced, not hidden. |
| `adaptive` | DeepL first; on **any** DeepL error fall back to the LLM. Once DeepL reports a service failure (quota/rate/auth) it is skipped for the rest of the run. |

Notes:

- The engine controls the **text translation** step. Text embedded in images is always
  OCR'd by the vision LLM (DeepL cannot OCR); the translate-after-OCR step then honors the
  selected engine.
- DeepL does not support all 24 EU languages — **Maltese (`mt`)** and **Irish (`ga`)** are
  not available. In `deepl` mode these targets return a hard error; in `adaptive` mode they
  fall back to the LLM.
- DeepL requires a regional variant for English and Portuguese targets; defaults are
  `EN-GB` / `PT-PT`, configurable via `DEEPL_EN_VARIANT` / `DEEPL_PT_VARIANT`.

## CLI Usage

### 1) Direct engine (recommended for layout fidelity)

```bash
python cli.py \
  --pdf-in input/document.pdf \
  --workdir ./work \
  --target-lang es \
  --layout-engine direct \
  --engine adaptive \
  --pdf-out output/
```

`--engine` selects the translation backend (`llm` | `deepl` | `adaptive`) and applies to
all input types; it is independent of `--layout-engine`. Omit it to use the
`TRANSLATION_ENGINE` env default (`llm`).

### 2) HTML engine (advanced/fallback)

```bash
python cli.py \
  --pdf-in input/document.pdf \
  --workdir ./work \
  --target-lang es \
  --layout-engine html \
  --pdf-out output/
```

### 3) JSON mapping replacement (HTML engine)

```bash
python cli.py \
  --pdf-in input/document.pdf \
  --workdir ./work \
  --mapping-json replacements.json \
  --layout-engine html \
  --pdf-out output/
```

`replacements.json` format:

```json
{
  "Hello": "Hola",
  "Summary": "Resumen"
}
```

### 4) TXT / DOCX / PPTX / DOC / PPT

```bash
python cli.py \
  --document-in input/document.docx \
  --workdir ./work \
  --target-lang es \
  --pdf-out output/
```

Notes:

- `.txt`, `.docx`, and `.pptx` are translated natively
- `.doc` and `.ppt` are converted to `.docx` / `.pptx` first when LibreOffice/`soffice` is available
- for non-PDF documents, `--layout-engine html`, `--mapping-json`, and `--save-html` are not used

### Output naming behavior

If `--pdf-out` is a directory, output is auto-named as:
- `<input_stem>_<target_lang>.pdf` (translation)
- `<input_stem>_mapped.pdf` (mapping mode)
- for non-PDF documents, the original extension is preserved where possible

## FastAPI Usage

Run server (local dev, port **15000** by default — override with `HOST`/`PORT`):

```bash
bash run.sh
```

Health:

```bash
curl -u "$BASIC_AUTH_USERNAME:$BASIC_AUTH_PASSWORD" http://localhost:15000/health
```

Docs:

```bash
curl -u "$BASIC_AUTH_USERNAME:$BASIC_AUTH_PASSWORD" http://localhost:15000/docs
```

Translate a supported document (`/translate/document`):

```bash
curl -X POST "http://localhost:15000/translate/document" \
  -u "$BASIC_AUTH_USERNAME:$BASIC_AUTH_PASSWORD" \
  -F "file=@input/document.pdf" \
  -F "target_lang=es" \
  -F "engine=adaptive" \
  -o output/document_es.pdf
```

The public API exposes a single translation endpoint. It currently supports
`.pdf`, `.txt`, `.doc`, `.docx`, `.ppt`, and `.pptx`. Formula-heavy or
equation-heavy PDFs are rejected before translation. The optional `engine` field
accepts `llm`, `deepl`, or `adaptive`; omit it to use the `TRANSLATION_ENGINE`
server default.

The legacy `/translate/pdf` and `/translate/pdf/advanced` routes are hidden from
OpenAPI and kept only as compatibility/internal routes during migration.

## Testing

See [TESTING.md](./TESTING.md) for the fast unit suite, regression suite, and full EU
translation matrix commands. Quick reference:

```bash
TRANSLATION_ENGINE=llm ./run_tests.sh   # fast unit suite (unittest, not pytest)
./run_regression_tests.sh               # cases from tests/integration_cases.json
```

Regression outputs and artifacts are written under `output/regression/`. The regression
suite covers representative PDF cases plus one TXT, one DOCX, and one PPTX fixture.

## Bulk EU Translation Matrix

To translate every supported file in `input/` into all 24 EU languages, run:

```bash
./run_all_eu_translations.sh
```

Outputs are written under `output/eu_translations/<lang>/`, with per-job logs in
`output/eu_translations/_logs/` (including a `*.stats.json` sidecar per job) and a
machine-readable manifest at `output/eu_translations/manifest.json`. The runner
prints the resolved engine, start/finish timestamps, and per-translation
duration; the manifest stores the same timing fields **plus each job's translation
`stats` and derived `quality_flags`**. A job that finished but still shows
`residual_source_text` (translatable text left in the source language),
`unplaced_blocks`, or rejected text/image segments is counted under `flagged` in
the summary and carries those flags in the manifest — a QA signal to review
without eyeballing every output. By default the script auto-detects each file's source
language; when a target language matches the detected source, the original file
is copied as that language's artifact so each input still has a 24-language
output set. Set `SOURCE_LANG` explicitly only when the whole input set is known
to share one language — declaring a wrong source silently mistranslates every
non-matching document.

Useful overrides:

```bash
ENGINE=adaptive ./run_all_eu_translations.sh
SOURCE_LANG=en ./run_all_eu_translations.sh
OVERWRITE=1 ./run_all_eu_translations.sh
TRANSLATE_IMAGE_TEXT=1 ./run_all_eu_translations.sh   # also OCR+translate text inside figures/diagrams/images
INPUT_DIR=/path/to/input OUTPUT_DIR=/path/to/output ./run_all_eu_translations.sh
```

The runner intentionally uses the same CLI pipeline as the application. It is a
long-running integration utility, not part of the normal unit test script.

## Docker

The container listens on port **9000** (see `Dockerfile` / `docker-compose.yml`);
the local `run.sh` dev server uses port 15000.

Build and run with Docker:

```bash
docker build -t omnilingua .
docker run --rm -p 9000:9000 --env-file .env omnilingua
```

Build and run with Compose:

```bash
docker compose up --build
```

Then call:

```bash
curl -u "$BASIC_AUTH_USERNAME:$BASIC_AUTH_PASSWORD" http://localhost:9000/health
```

Push (the compose service `omnilingua` has an `image:` tag):

```bash
docker compose build omnilingua
docker compose push omnilingua
```

Notes:

- The image bundles poppler-utils, DejaVu/Noto fonts, and Playwright Chromium.
- The image does **not** include LibreOffice, so legacy `.doc`/`.ppt` conversion is
  unavailable in Docker unless you add it to the `Dockerfile`.

## Project Structure

```text
omnilingua/
├── app/
│   ├── main.py                          # FastAPI bootstrap (basic auth on ALL routes, incl. /docs)
│   ├── api/
│   │   └── routes/
│   │       ├── health.py                # GET /health
│   │       └── translate.py             # POST /translate/document (+ hidden PDF compat routes)
│   ├── core/
│   │   ├── auth.py                      # HTTP basic auth
│   │   ├── engines.py                   # llm | deepl | adaptive selection and validation
│   │   ├── languages.py                 # the 24 EU language codes
│   │   └── model_config.py              # env resolution (incl. legacy fallback names)
│   ├── services/
│   │   ├── document_translate_service.py  # /translate/document validation + routing
│   │   └── pdf_translate_service.py       # PDF compat/advanced (html engine) orchestration
│   └── pipeline/
│       ├── block_schema.py
│       ├── extract_native_blocks.py     # PDF structure extraction (direct engine)
│       ├── translate_pdf_direct.py      # direct engine orchestration
│       ├── pdf_content_policy.py        # formula/equation-heavy PDF rejection
│       ├── protected_text.py            # URL/email/@handle token protection
│       ├── fonts.py                     # glyph-aware font fallback
│       ├── language_metrics.py          # measured EN→target text expansion factors
│       ├── translator_factory.py        # backend selection
│       ├── translator_llm.py            # OpenAI-compatible backend (+ HTML node translation)
│       ├── translator_deepl.py          # DeepL backend
│       ├── translator_adaptive.py       # DeepL-with-LLM-fallback backend
│       ├── translate_text_segments.py   # shared segment translation core
│       ├── translate_txt.py             # native .txt
│       ├── translate_docx.py            # native .docx
│       ├── translate_pptx.py            # native .pptx
│       ├── convert_legacy_office.py     # .doc/.ppt -> .docx/.pptx via LibreOffice
│       ├── convert_pdf_to_html.py       # html engine: Poppler pdftohtml
│       ├── replace_html_text.py         # html engine: JSON mapping replacement
│       ├── render_html_to_pdf.py        # html engine: Playwright Chromium rendering
│       ├── pdf_page_size.py             # html engine: source page geometry
│       ├── playwright_support.py        # html engine: Chromium install check
│       ├── translate_pdf_image_text.py  # experimental image-embedded text (direct engine)
│       ├── translate_html_image_text.py # experimental image-embedded text (html engine)
│       └── vision_llm.py                # vision model OCR client
├── cli.py
├── docs/                                # flow-technical.html, omnilingua_qna.html
├── tests/
├── scripts/
├── run.sh                               # local dev server (port 15000)
├── run_tests.sh
├── run_regression_tests.sh
├── run_all_eu_translations.sh
├── requirements.txt
├── Dockerfile / docker-compose.yml
├── TESTING.md
├── .env.sample
└── README.md
```

## Structured Files Guidance

This project is currently a PDF translation service. It does not translate JSON, CSV, or XLSX files directly.

If support for those formats is considered later, the safe rule is:

- translate presentation text
- do not translate operational or canonical data in place

Practical guidance:

- i18n JSON such as `i18n/en.json`: translate values only, never keys
- config/API JSON/database exports: do not translate in place
- user-facing CSV/XLSX reports or catalogs: translate selectively
- raw datasets, exports, IDs, codes, slugs, enums, and programmatic column names: do not translate

Why this matters:

- translating JSON keys or technical values can break parsing and application behavior
- translating dataset identifiers or programmatic headers can break joins, pipelines, and downstream code
- dates, currencies, numbers, format strings, URLs, and placeholders often require preservation rather than translation

The safest long-term approach for structured formats is to extract translatable strings into a dedicated localization layer and keep data files in their canonical form.

## Notes

- `/translate/document` is the public translation endpoint.
- It currently supports `.pdf`, `.txt`, `.doc`, `.docx`, `.ppt`, and `.pptx`.
- Formula-heavy or equation-heavy PDFs are rejected with HTTP 400.
- PDF-specific routes are hidden compatibility/internal routes, not intended for end users.
- Structured formats such as `.json`, `.csv`, `.xls`, and `.xlsx` need dedicated extraction/rebuild support before they should be accepted.
- `work/` and `output/` are generated artifacts and should not be committed.
- Regression test outputs are written under `output/regression/`.
