#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
INPUT_DIR="${INPUT_DIR:-input}"
OUTPUT_DIR="${OUTPUT_DIR:-output/eu_translations}"
SOURCE_LANG="${SOURCE_LANG:-en}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python interpreter not found or not executable: $PYTHON_BIN" >&2
  exit 1
fi

cmd=(
  "$PYTHON_BIN"
  scripts/translate_input_to_all_eu_languages.py
  --input-dir "$INPUT_DIR"
  --output-dir "$OUTPUT_DIR"
  --source-lang "$SOURCE_LANG"
)

if [[ -n "${ENGINE:-}" ]]; then
  cmd+=(--engine "$ENGINE")
fi

if [[ "${OVERWRITE:-0}" == "1" ]]; then
  cmd+=(--overwrite)
fi

if [[ "${AUTO_SOURCE:-0}" == "1" ]]; then
  cmd+=(--auto-source)
fi

exec "${cmd[@]}"
