from __future__ import annotations

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile
from fastapi.responses import FileResponse

from app.services.document_translate_service import (
    cleanup_dir as cleanup_document_dir,
    detect_media_type,
    run_document_translation,
)
from app.services.pdf_translate_service import cleanup_dir, run_translation


router = APIRouter()


CommonFile = Annotated[
    UploadFile,
    File(
        description="Born-digital PDF file to translate.",
        media_type="application/pdf",
        json_schema_extra={
            "contentMediaType": "application/pdf",
        },
    ),
]
DocumentFile = Annotated[
    UploadFile,
    File(
        description="Supported document file to translate (.pdf, .txt, .doc, .docx, .ppt, .pptx).",
    ),
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
CommonEngine = Annotated[
    Optional[str],
    Form(
        description=(
            "Translation backend: 'llm' (default), 'deepl', or 'adaptive' (DeepL first, "
            "fall back to LLM on any DeepL error). Leave empty to use the TRANSLATION_ENGINE "
            "server default."
        ),
        examples=["adaptive"],
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
    openapi_extra={
        "requestBody": {
            "content": {
                "multipart/form-data": {
                    "encoding": {
                        "file": {"contentType": "application/pdf"}
                    }
                }
            }
        }
    },
)
async def translate_pdf(
    background_tasks: BackgroundTasks,
    file: CommonFile,
    target_lang: CommonTargetLang = None,
    source_lang: CommonSourceLang = None,
    engine: CommonEngine = None,
) -> FileResponse:
    result = await run_translation(
        file=file,
        target_lang=target_lang,
        source_lang=source_lang,
        layout_engine="direct",
        save_html=False,
        mapping_json=None,
        translate_image_text=False,
        engine=engine,
    )
    background_tasks.add_task(cleanup_dir, result.tmp_root)
    return FileResponse(
        path=result.output_pdf,
        media_type="application/pdf",
        filename=result.output_pdf.name,
    )


@router.post(
    "/translate/document",
    summary="Translate a document",
    description="Translate a supported document file. Supports .pdf, .txt, .doc, .docx, .ppt, and .pptx.",
)
async def translate_document(
    background_tasks: BackgroundTasks,
    file: DocumentFile,
    target_lang: CommonTargetLang = None,
    source_lang: CommonSourceLang = None,
    engine: CommonEngine = None,
) -> FileResponse:
    result = await run_document_translation(
        file=file,
        target_lang=target_lang,
        source_lang=source_lang,
        engine=engine,
    )
    background_tasks.add_task(cleanup_document_dir, result.tmp_root)
    return FileResponse(
        path=result.output_path,
        media_type=detect_media_type(result.output_path),
        filename=result.output_path.name,
    )


@router.post(
    "/translate/pdf/advanced",
    summary="Translate or replace PDF text (advanced)",
    description="Advanced endpoint for choosing html/direct mode, saving intermediate HTML, or using mapping_json exact replacements instead of translation.",
    openapi_extra={
        "requestBody": {
            "content": {
                "multipart/form-data": {
                    "encoding": {
                        "file": {"contentType": "application/pdf"}
                    }
                }
            }
        }
    },
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
    engine: CommonEngine = None,
) -> FileResponse:
    result = await run_translation(
        file=file,
        target_lang=target_lang,
        source_lang=source_lang,
        layout_engine=layout_engine,
        save_html=save_html,
        mapping_json=mapping_json,
        translate_image_text=translate_image_text,
        engine=engine,
    )
    background_tasks.add_task(cleanup_dir, result.tmp_root)
    return FileResponse(
        path=result.output_pdf,
        media_type="application/pdf",
        filename=result.output_pdf.name,
    )
