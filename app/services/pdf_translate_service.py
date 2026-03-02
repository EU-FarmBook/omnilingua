from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from fastapi import HTTPException, UploadFile

from app.pipeline.convert_pdf_to_html import convert_pdf_to_html
from app.pipeline.pdf_page_size import get_first_page_size
from app.pipeline.render_html_to_pdf import render_html_to_pdf
from app.pipeline.replace_html_text import replace_text_nodes
from app.pipeline.translate_pdf_direct import translate_pdf_direct
from app.pipeline.translator_llm import translate_html_content


LayoutEngine = Literal["html", "direct"]


@dataclass(frozen=True)
class TranslationResult:
    tmp_root: str
    output_pdf: Path


def cleanup_dir(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)


def safe_stem(name: str) -> str:
    stem = Path(name).stem or "document"
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stem)
    return safe[:120] or "document"


def validate_request(
    filename: str | None,
    target_lang: Optional[str],
    layout_engine: LayoutEngine,
    mapping_json: Optional[str],
) -> None:
    if not filename or not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a .pdf")
    if layout_engine == "direct" and not target_lang:
        raise HTTPException(status_code=400, detail="target_lang is required for layout_engine=direct")
    if mapping_json and target_lang:
        raise HTTPException(status_code=400, detail="Use either mapping_json or target_lang, not both")


async def run_translation(
    file: UploadFile,
    target_lang: Optional[str],
    source_lang: Optional[str],
    layout_engine: LayoutEngine,
    save_html: bool,
    mapping_json: Optional[str],
) -> TranslationResult:
    validate_request(file.filename, target_lang, layout_engine, mapping_json)

    tmp_root = tempfile.mkdtemp(prefix="doc_generator_api_")
    safe_name = safe_stem(file.filename or "document.pdf")
    in_pdf = Path(tmp_root) / f"{safe_name}.pdf"
    out_dir = Path(tmp_root) / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    suffix = target_lang or ("mapped" if mapping_json else "out")
    out_pdf = out_dir / f"{safe_name}_{suffix}.pdf"

    data = await file.read()
    in_pdf.write_bytes(data)

    try:
        if layout_engine == "direct":
            translate_pdf_direct(
                pdf_in=in_pdf,
                pdf_out=out_pdf,
                target_lang=target_lang or "",
                source_lang=source_lang,
            )
            return TranslationResult(tmp_root=tmp_root, output_pdf=out_pdf)

        page_size = get_first_page_size(in_pdf)
        html_dir = Path(tmp_root) / "work" / "html"
        html_dir.mkdir(parents=True, exist_ok=True)

        html_original = convert_pdf_to_html(in_pdf, html_dir)
        html_for_pdf = html_original

        if target_lang:
            html_translated = html_dir / (in_pdf.stem + ".translated.html")
            translate_html_content(
                html_original,
                html_translated,
                target_lang=target_lang,
                source_lang=source_lang,
            )
            html_for_pdf = html_translated
        elif mapping_json:
            try:
                mapping = json.loads(mapping_json)
                if not isinstance(mapping, dict):
                    raise ValueError("mapping_json must decode to an object")
                mapping = {str(k): str(v) for k, v in mapping.items()}
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Invalid mapping_json: {exc}") from exc
            html_translated = html_dir / (in_pdf.stem + ".translated.html")
            replace_text_nodes(html_original, html_translated, mapping)
            html_for_pdf = html_translated

        has_text_changes = html_for_pdf != html_original
        render_html_to_pdf(
            html_for_pdf,
            out_pdf,
            page_size=page_size,
            adjust_text_overflow=has_text_changes,
            hide_background_images=has_text_changes,
        )

        if save_html:
            export_dir = out_dir / "html"
            export_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(html_original, export_dir / html_original.name)
            if html_for_pdf != html_original and html_for_pdf.exists():
                shutil.copy2(html_for_pdf, export_dir / html_for_pdf.name)

        return TranslationResult(tmp_root=tmp_root, output_pdf=out_pdf)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Translation pipeline failed: {exc}") from exc
