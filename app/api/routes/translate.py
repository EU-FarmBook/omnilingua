from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile
from fastapi.responses import FileResponse

from app.services.pdf_translate_service import cleanup_dir, run_translation


router = APIRouter()


@router.post("/translate/pdf")
async def translate_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    target_lang: Optional[str] = Form(default=None),
    source_lang: Optional[str] = Form(default=None),
    layout_engine: Literal["html", "direct"] = Form(default="html"),
    save_html: bool = Form(default=False),
    mapping_json: Optional[str] = Form(default=None),
) -> FileResponse:
    result = await run_translation(
        file=file,
        target_lang=target_lang,
        source_lang=source_lang,
        layout_engine=layout_engine,
        save_html=save_html,
        mapping_json=mapping_json,
    )
    background_tasks.add_task(cleanup_dir, result.tmp_root)
    return FileResponse(
        path=result.output_pdf,
        media_type="application/pdf",
        filename=result.output_pdf.name,
    )

