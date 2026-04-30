# Doc Generator

Translate born-digital PDFs while preserving layout as much as possible.

This project supports two engines:
- `direct`: the standard production path
- `html`: advanced/fallback `PDF -> HTML -> translate/replace -> PDF`

## Features

- CLI workflow for translation and JSON mapping replacement
- FastAPI endpoint for upload + translated PDF download
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
```

Legacy names are still accepted as fallbacks for backward compatibility:

- text model: `TEXT_URL`, `TEXT_API_KEY`, `TEXT_MODEL`, `RUNPOD_VLLM_HOST`, `VLLM_API_KEY`, `VLLM_MODEL`
- vision model: `VISION_URL`, `VISION_API_KEY`, `VISION_MODEL`

## CLI Usage

### 1) Direct engine (recommended for layout fidelity)

```bash
python cli.py \
  --pdf-in input/document.pdf \
  --workdir ./work \
  --target-lang es \
  --layout-engine direct \
  --pdf-out output/
```

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

### Output naming behavior

If `--pdf-out` is a directory, output is auto-named as:
- `<input_stem>_<target_lang>.pdf` (translation)
- `<input_stem>_mapped.pdf` (mapping mode)

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
  -o output/document_es.pdf
```

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

## Notes

- `direct` engine is usually better for complex layouts.
- `/translate/pdf` is the recommended path and always uses `direct`.
- `html` remains available only through `/translate/pdf/advanced`.
- `html` engine can be useful when preserving HTML intermediates is important.
- `translate_image_text` is experimental and available only through the advanced direct flow.
- `work/` and `output/` are generated artifacts and should not be committed.
- Regression test outputs are written under `output/regression/`.
