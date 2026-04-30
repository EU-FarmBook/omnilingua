from __future__ import annotations

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile
from fastapi.responses import FileResponse

from app.services.pdf_translate_service import cleanup_dir, run_translation


router = APIRouter()


CommonFile = Annotated[
    UploadFile,
    File(description="Born-digital PDF file to translate."),
]
CommonTargetLang = Annotated[
    Optional[str],
    Form(
        description="Required target language. Two-letter EU language code such as 'el', 'es', or 'de'.",
        examples=["el"],
    ),
]
CommonSourceLang = Annotated[
    Optional[str],
    Form(
        description="Optional source language. Leave empty to auto-detect. Use a two-letter EU language code such as 'en'.",
        examples=["en"],
    ),
]
CommonLayoutEngine = Annotated[
    Literal["html", "direct"],
    Form(
        description="Translation engine. 'direct' is recommended for better layout fidelity.",
    ),
]
AdvancedSaveHtml = Annotated[
    bool,
    Form(
        description="Advanced: save intermediate HTML files in the output bundle.",
    ),
]
AdvancedMappingJson = Annotated[
    Optional[str],
    Form(
        description=(
            "Advanced alternative to translation. Provide a JSON object of exact text replacements, "
            "for example {\"Hello\": \"Hola\"}. Leave empty for normal translation."
        ),
    ),
]
AdvancedTranslateImageText = Annotated[
    bool,
    Form(
        description="Experimental: translate text embedded inside images when using the direct engine.",
    ),
]


@router.post(
    "/translate/pdf",
    summary="Translate a PDF",
    description="Common translation endpoint. Uses the recommended direct engine automatically.",
)
async def translate_pdf(
    background_tasks: BackgroundTasks,
    file: CommonFile,
    target_lang: CommonTargetLang = None,
    source_lang: CommonSourceLang = None,
) -> FileResponse:
    result = await run_translation(
        file=file,
        target_lang=target_lang,
        source_lang=source_lang,
        layout_engine="direct",
        save_html=False,
        mapping_json=None,
        translate_image_text=False,
    )
    background_tasks.add_task(cleanup_dir, result.tmp_root)
    return FileResponse(
        path=result.output_pdf,
        media_type="application/pdf",
        filename=result.output_pdf.name,
    )


@router.post(
    "/translate/pdf/advanced",
    summary="Translate or replace PDF text (advanced)",
    description="Advanced endpoint for choosing html/direct mode, saving intermediate HTML, or using mapping_json exact replacements instead of translation.",
)
async def translate_pdf_advanced(
    background_tasks: BackgroundTasks,
    file: CommonFile,
    target_lang: CommonTargetLang = None,
    source_lang: CommonSourceLang = None,
    layout_engine: CommonLayoutEngine = "direct",
    save_html: AdvancedSaveHtml = False,
    mapping_json: AdvancedMappingJson = None,
    translate_image_text: AdvancedTranslateImageText = False,
) -> FileResponse:
    result = await run_translation(
        file=file,
        target_lang=target_lang,
        source_lang=source_lang,
        layout_engine=layout_engine,
        save_html=save_html,
        mapping_json=mapping_json,
        translate_image_text=translate_image_text,
    )
    background_tasks.add_task(cleanup_dir, result.tmp_root)
    return FileResponse(
        path=result.output_pdf,
        media_type="application/pdf",
        filename=result.output_pdf.name,
    )
