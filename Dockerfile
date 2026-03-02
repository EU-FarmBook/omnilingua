FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System dependencies:
# - poppler-utils: pdftohtml/pdfinfo/pdftotext (html engine)
# - fonts-dejavu-core: Unicode glyph fallback (direct engine for Greek/Cyrillic/etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    fonts-dejavu-core \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium + runtime deps for Playwright (html engine).
RUN playwright install --with-deps chromium

COPY . .

EXPOSE 9000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]

