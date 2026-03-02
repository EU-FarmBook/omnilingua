# Doc Generator

Translate born-digital PDFs while preserving layout as much as possible.

This project supports two engines:
- `html`: `PDF -> HTML -> translate/replace -> PDF`
- `direct`: direct PDF line translation + rewrite on original PDF coordinates

## Features

- CLI workflow for translation and JSON mapping replacement
- FastAPI endpoint for upload + translated PDF download
- Auto language detection (or manual `--source-lang`)
- Output auto-naming with language suffix when output is a directory
- Modular app structure (`app/api`, `app/services`, `app/pipeline`)

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
RUNPOD_VLLM_HOST=
VLLM_API_KEY=
VLLM_MODEL=
DEFAULT_NUM_PREDICT=
COMBINE_NUM_PREDICT=
PER_REQUEST_TIMEOUT=
BASIC_AUTH_USERNAME=
BASIC_AUTH_PASSWORD=
```

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

### 2) HTML engine

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
uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload
```

Health:

```bash
curl -u "$BASIC_AUTH_USERNAME:$BASIC_AUTH_PASSWORD" http://localhost:9000/health
```

Docs:

```bash
curl -u "$BASIC_AUTH_USERNAME:$BASIC_AUTH_PASSWORD" http://localhost:9000/docs
```

Translate PDF (`direct`):

```bash
curl -X POST "http://localhost:9000/translate/pdf" \
  -u "$BASIC_AUTH_USERNAME:$BASIC_AUTH_PASSWORD" \
  -F "file=@input/document.pdf" \
  -F "target_lang=es" \
  -F "layout_engine=direct" \
  -o output/document_es.pdf
```

Translate PDF (`html`):

```bash
curl -X POST "http://localhost:9000/translate/pdf" \
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

Push (if `docker-compose.yml` has service `omnilingua` with an `image:` tag):

```bash
docker compose build omnilingua
docker compose push omnilingua
```

## Project Structure

```text
doc_generator/
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
│       ├── replace_html_text.py
│       ├── pdf_page_size.py
│       ├── render_html_to_pdf.py
│       ├── translator_llm.py
│       └── translate_pdf_direct.py
├── cli.py
├── requirements.txt
├── ARCHITECTURE.md
├── .env.sample
└── README.md
```

## Notes

- `direct` engine is usually better for complex layouts.
- `html` engine can be useful when preserving HTML intermediates is important.
- `work/` and `output/` are generated artifacts and should not be committed.
