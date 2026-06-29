# Doc Generator

Translate born-digital PDFs and selected office/text documents while preserving structure as much as possible.

This project supports:
- native document translation for `txt`, `docx`, and `pptx`
- conversion-assisted support for legacy `doc` and `ppt` when LibreOffice/`soffice` is available
- two PDF engines:
  - `direct`: the standard production path
  - `html`: advanced/fallback `PDF -> HTML -> translate/replace -> PDF`
- three translation backends (`llm`, `deepl`, `adaptive`) — see [Translation engines](#translation-engines)

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
- Modular app structure (`app/api`, `app/services`, `app/pipeline`)
- Unit and regression test entrypoints

## Requirements

- Python 3.10+
- Poppler tools (`pdftohtml`, `pdftotext`, `pdfinfo`) for `html` engine
- Playwright Chromium for `html` engine
- OpenAI-compatible LLM endpoint
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

Run server:

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

Translate PDF (`/translate/pdf`, standard direct path):

```bash
curl -X POST "http://localhost:15000/translate/pdf" \
  -u "$BASIC_AUTH_USERNAME:$BASIC_AUTH_PASSWORD" \
  -F "file=@input/document.pdf" \
  -F "target_lang=es" \
  -F "engine=adaptive" \
  -o output/document_es.pdf
```

All translation endpoints (`/translate/pdf`, `/translate/document`,
`/translate/pdf/advanced`) accept an optional `engine` field (`llm` | `deepl` | `adaptive`);
omit it to use the `TRANSLATION_ENGINE` server default.

Advanced direct translation with image-text enabled:

```bash
curl -X POST "http://localhost:15000/translate/pdf/advanced" \
  -u "$BASIC_AUTH_USERNAME:$BASIC_AUTH_PASSWORD" \
  -F "file=@input/document.pdf" \
  -F "target_lang=es" \
  -F "layout_engine=direct" \
  -F "translate_image_text=true" \
  -o output/document_es.pdf
```

Advanced HTML translation:

```bash
curl -X POST "http://localhost:15000/translate/pdf/advanced" \
  -u "$BASIC_AUTH_USERNAME:$BASIC_AUTH_PASSWORD" \
  -F "file=@input/document.pdf" \
  -F "target_lang=es" \
  -F "layout_engine=html" \
  -o output/document_es_html.pdf
```

Translate a supported document (`/translate/document`):

```bash
curl -X POST "http://localhost:15000/translate/document" \
  -u "$BASIC_AUTH_USERNAME:$BASIC_AUTH_PASSWORD" \
  -F "file=@input/document.docx" \
  -F "target_lang=es" \
  -o output/document_es.docx
```

## Docker

Build and run with Docker:

```bash
docker build -t omnilingua .
docker run --rm -p 15000:15000 --env-file .env omnilingua
```

Build and run with Compose:

```bash
docker compose up --build
```

Then call:

```bash
curl -u "$BASIC_AUTH_USERNAME:$BASIC_AUTH_PASSWORD" http://localhost:15000/health
```

Push (if `docker-compose.yml` has service `omnilingua` with an `image:` tag):

```bash
docker compose build omnilingua
docker compose push omnilingua
```

## Project Structure

```text
omnilingua/
├── app/
│   ├── main.py
│   ├── api/
│   │   └── routes/
│   │       ├── health.py
│   │       └── translate.py
│   ├── services/
│   │   └── pdf_translate_service.py
│   └── pipeline/
│       ├── convert_pdf_to_html.py
│       ├── extract_native_blocks.py
│       ├── fonts.py
│       ├── translate_pdf_image_text.py
│       ├── replace_html_text.py
│       ├── pdf_page_size.py
│       ├── render_html_to_pdf.py
│       ├── translator_llm.py
│       └── translate_pdf_direct.py
├── cli.py
├── run.sh
├── run_tests.sh
├── run_regression_tests.sh
├── tests/
├── requirements.txt
├── ARCHITECTURE.md
├── .env.sample
└── README.md
```

## Tests

Run the unit test suite:

```bash
./run_tests.sh
```

Run regression translations for the cases listed in `tests/integration_cases.json`:

```bash
./run_regression_tests.sh
```

Regression outputs and artifacts are written under `output/regression/`.

The regression suite now covers:

- representative PDF cases
- one TXT fixture
- one DOCX fixture
- one PPTX fixture

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

- `direct` engine is usually better for complex layouts.
- `/translate/pdf` is the recommended path and always uses `direct`.
- `/translate/document` supports `.pdf`, `.txt`, `.doc`, `.docx`, `.ppt`, and `.pptx`.
- `html` remains available only through `/translate/pdf/advanced`.
- `html` engine can be useful when preserving HTML intermediates is important.
- `translate_image_text` is experimental and available only through the advanced direct flow.
- `work/` and `output/` are generated artifacts and should not be committed.
- Regression test outputs are written under `output/regression/`.
