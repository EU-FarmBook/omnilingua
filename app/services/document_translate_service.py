from __future__ import annotations

import mimetypes
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile

from app.core.engines import is_deepl_supported, validate_engine
from app.core.languages import EU_LANGUAGE_NAMES, validate_optional_language_code
from app.pipeline.convert_legacy_office import convert_legacy_office_document
from app.pipeline.translate_docx import translate_docx
from app.pipeline.translate_pdf_direct import translate_pdf_direct
from app.pipeline.translate_pptx import translate_pptx
from app.pipeline.translate_txt import translate_txt


SUPPORTED_DOCUMENT_EXTENSIONS = frozenset({".pdf", ".txt", ".doc", ".docx", ".ppt", ".pptx"})


@dataclass(frozen=True)
class DocumentTranslationResult:
    tmp_root: str
    output_path: Path


def cleanup_dir(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)


def safe_stem(name: str) -> str:
    stem = Path(name).stem or "document"
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stem)
    return safe[:120] or "document"


def normalize_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def detect_media_type(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return "application/pdf"
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def validate_document_request(
    filename: str | None,
    target_lang: Optional[str],
    source_lang: Optional[str],
    engine: Optional[str] = None,
) -> tuple[str, str, Optional[str], str]:
    target_lang = normalize_optional_text(target_lang)
    source_lang = normalize_optional_text(source_lang)

    if not filename:
        raise HTTPException(status_code=400, detail="Uploaded file is required")

    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported file type. Supported extensions: "
                + ", ".join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))
            ),
        )
    if not target_lang:
        raise HTTPException(status_code=400, detail="target_lang is required")

    try:
        normalized_engine = validate_engine(engine)
        normalized_target = validate_optional_language_code(target_lang, "target_lang")
        normalized_source = validate_optional_language_code(source_lang, "source_lang")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if normalized_target and normalized_source and normalized_target == normalized_source:
        raise HTTPException(
            status_code=400,
            detail="source_lang and target_lang must be different when both are provided",
        )

    if (
        normalized_engine == "deepl"
        and normalized_target
        and not is_deepl_supported(normalized_target)
    ):
        name = EU_LANGUAGE_NAMES.get(normalized_target, normalized_target)
        raise HTTPException(
            status_code=400,
            detail=(
                f"DeepL does not support translation into {name} ('{normalized_target}'). "
                f"Use engine 'llm' or 'adaptive' for this language."
            ),
        )

    return (suffix, normalized_target or "", normalized_source, normalized_engine)


async def run_document_translation(
    file: UploadFile,
    *,
    target_lang: Optional[str],
    source_lang: Optional[str],
    engine: Optional[str] = None,
) -> DocumentTranslationResult:
    suffix, target_lang, source_lang, engine = validate_document_request(
        file.filename,
        target_lang,
        source_lang,
        engine,
    )

    tmp_root = tempfile.mkdtemp(prefix="omnilingua_document_api_")
    safe_name = safe_stem(file.filename or f"document{suffix}")
    in_path = Path(tmp_root) / f"{safe_name}{suffix}"
    out_dir = Path(tmp_root) / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    output_suffix = suffix
    if suffix == ".doc":
        output_suffix = ".docx"
    elif suffix == ".ppt":
        output_suffix = ".pptx"
    out_path = out_dir / f"{safe_name}_{target_lang}{output_suffix}"

    in_path.write_bytes(await file.read())

    try:
        actual_input = in_path
        actual_suffix = suffix

        if suffix == ".doc":
            actual_input = convert_legacy_office_document(in_path, output_suffix=".docx", output_dir=Path(tmp_root) / "converted")
            actual_suffix = ".docx"
        elif suffix == ".ppt":
            actual_input = convert_legacy_office_document(in_path, output_suffix=".pptx", output_dir=Path(tmp_root) / "converted")
            actual_suffix = ".pptx"

        if actual_suffix == ".pdf":
            translate_pdf_direct(
                pdf_in=actual_input,
                pdf_out=out_path,
                target_lang=target_lang,
                source_lang=source_lang,
                translate_image_text=False,
                engine=engine,
            )
        elif actual_suffix == ".txt":
            translate_txt(
                actual_input,
                out_path,
                target_lang=target_lang,
                source_lang=source_lang,
                engine=engine,
            )
        elif actual_suffix == ".docx":
            translate_docx(
                actual_input,
                out_path,
                target_lang=target_lang,
                source_lang=source_lang,
                engine=engine,
            )
        elif actual_suffix == ".pptx":
            translate_pptx(
                actual_input,
                out_path,
                target_lang=target_lang,
                source_lang=source_lang,
                engine=engine,
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {actual_suffix}")

        return DocumentTranslationResult(tmp_root=tmp_root, output_path=out_path)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Translation pipeline failed: {exc}") from exc
