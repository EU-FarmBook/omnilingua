# cli.py

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.core.engines import is_deepl_supported, validate_engine
from app.core.languages import EU_LANGUAGE_NAMES, validate_optional_language_code
from app.pipeline.convert_legacy_office import convert_legacy_office_document
from app.pipeline.pdf_content_policy import PdfContentPolicyError
from app.pipeline.convert_pdf_to_html import convert_pdf_to_html
from app.pipeline.playwright_support import ensure_chromium_installed
from app.pipeline.replace_html_text import load_mapping, replace_text_nodes
from app.pipeline.render_html_to_pdf import render_html_to_pdf
from app.pipeline.pdf_page_size import get_first_page_size
from app.pipeline.translate_docx import translate_docx
from app.pipeline.translate_pptx import translate_pptx
from app.pipeline.translator_llm import translate_html_content
from app.pipeline.translate_pdf_direct import translate_pdf_direct
from app.pipeline.translate_txt import translate_txt


SUPPORTED_DOCUMENT_EXTENSIONS = frozenset({".pdf", ".txt", ".doc", ".docx", ".ppt", ".pptx"})


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def resolve_output_path(
    out_arg: str,
    input_path: Path,
    target_lang: str | None,
    mapping_json: str | None,
) -> Path:
    """
    Resolve --pdf-out as either:
    - explicit PDF filepath, or
    - output directory (auto-name based on input + suffix).
    """
    raw = Path(out_arg).expanduser()
    out_path = raw.resolve()

    desired_suffix = input_path.suffix if input_path.suffix.lower() != ".doc" and input_path.suffix.lower() != ".ppt" else (
        ".docx" if input_path.suffix.lower() == ".doc" else ".pptx"
    )
    is_dir_like = raw.as_posix().endswith("/") or out_path.is_dir() or out_path.suffix.lower() != desired_suffix.lower()
    if not is_dir_like:
        return out_path

    suffix = target_lang if target_lang else ("mapped" if mapping_json else "out")
    return out_path / f"{input_path.stem}_{suffix}{desired_suffix}"


def main() -> int:
    """
    End-to-end PDF translator with LLM support.
    
    Workflow:
      1. PDF -> HTML (using pdftohtml)
      2. Translate HTML content (using LLM API)
      3. HTML -> PDF (using Playwright/Chromium)
    
    Features:
      - Automatic language detection
      - Preserves layout and formatting
      - Saves intermediate HTML files (optional)
    """
    ap = argparse.ArgumentParser(description="Document translator with LLM support.")
    ap.add_argument("--pdf-in", required=False, help="Input PDF path (backward-compatible alias).")
    ap.add_argument("--document-in", required=False, help="Input document path (.pdf, .txt, .doc, .docx, .ppt, .pptx).")
    ap.add_argument("--workdir", required=True, help="Working directory for intermediate files.")
    ap.add_argument("--mapping-json", required=False, default=None,
                    help="Optional JSON mapping of original text -> replacement text. If omitted, no text changes are applied.",
    )
    ap.add_argument("--target-lang", required=False, default=None,
                    help="Target language code for LLM translation (e.g., 'es', 'fr', 'de'). If provided, translates the document content.",
    )
    ap.add_argument("--source-lang", required=False, default=None,
                    help="Source language code (e.g., 'en', 'es'). Auto-detected if not provided.",
    )
    ap.add_argument(
        "--pdf-out",
        required=True,
                    help="Output file path, or output directory (auto-names as <input_stem>_<target_lang><ext>).",
    )
    ap.add_argument("--save-html", action="store_true",
                    help="Also save intermediate HTML files to the output directory.")
    ap.add_argument(
        "--translate-image-text",
        action="store_true",
        help="Experimental: translate text embedded inside images when using the direct engine.",
    )
    ap.add_argument(
        "--layout-engine",
        choices=("html", "direct"),
        default="direct",
        help="Pipeline engine: 'html' (pdftohtml round-trip) or 'direct' (PDF block rewrite).",
    )
    ap.add_argument(
        "--engine",
        choices=("llm", "deepl", "adaptive"),
        default=None,
        help=(
            "Translation backend: 'llm' (default), 'deepl', or 'adaptive' (DeepL first, "
            "fall back to LLM on any DeepL error). Defaults to the TRANSLATION_ENGINE env var."
        ),
    )
    args = ap.parse_args()

    input_arg = args.document_in or args.pdf_in
    if not input_arg:
        raise ValueError("Either --document-in or --pdf-in is required.")

    input_path = Path(input_arg).expanduser().resolve()
    workdir = Path(args.workdir).expanduser().resolve()
    args.target_lang = normalize_optional_text(args.target_lang)
    args.source_lang = normalize_optional_text(args.source_lang)
    args.mapping_json = normalize_optional_text(args.mapping_json)

    try:
        args.target_lang = validate_optional_language_code(args.target_lang, "target_lang")
        args.source_lang = validate_optional_language_code(args.source_lang, "source_lang")
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if args.target_lang and args.source_lang and args.target_lang == args.source_lang:
        raise ValueError("--source-lang and --target-lang must be different when both are provided.")

    args.engine = validate_engine(args.engine)
    if args.engine == "deepl" and args.target_lang and not is_deepl_supported(args.target_lang):
        name = EU_LANGUAGE_NAMES.get(args.target_lang, args.target_lang)
        raise ValueError(
            f"DeepL does not support translation into {name} ('{args.target_lang}'). "
            f"Use --engine llm or --engine adaptive for this language."
        )

    out_path = resolve_output_path(
        args.pdf_out,
        input_path=input_path,
        target_lang=args.target_lang,
        mapping_json=args.mapping_json,
    )

    if not input_path.exists():
        raise FileNotFoundError(f"Input document not found: {input_path}")

    suffix = input_path.suffix.lower()
    if suffix not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise ValueError(
            "Unsupported input type. Supported extensions: "
            + ", ".join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))
        )

    if suffix != ".pdf":
        if args.layout_engine != "direct":
            raise ValueError("--layout-engine html is supported only for PDF input.")
        if args.mapping_json:
            raise ValueError("--mapping-json is supported only for PDF input with --layout-engine html.")
        if args.save_html:
            raise ValueError("--save-html is supported only for PDF input with --layout-engine html.")
        if not args.target_lang:
            raise ValueError("--target-lang is required for non-PDF input.")

        actual_input = input_path
        actual_suffix = suffix
        if suffix == ".doc":
            actual_input = convert_legacy_office_document(input_path, output_suffix=".docx", output_dir=workdir / "converted")
            actual_suffix = ".docx"
        elif suffix == ".ppt":
            actual_input = convert_legacy_office_document(input_path, output_suffix=".pptx", output_dir=workdir / "converted")
            actual_suffix = ".pptx"

        if actual_suffix == ".txt":
            stats = translate_txt(
                actual_input,
                out_path,
                target_lang=args.target_lang,
                source_lang=args.source_lang,
                engine=args.engine,
            )
        elif actual_suffix == ".docx":
            stats = translate_docx(
                actual_input,
                out_path,
                target_lang=args.target_lang,
                source_lang=args.source_lang,
                engine=args.engine,
            )
        else:
            stats = translate_pptx(
                actual_input,
                out_path,
                target_lang=args.target_lang,
                source_lang=args.source_lang,
                engine=args.engine,
            )

        print(f"Source language: {stats.source_lang}")
        print(
            f"Segments translated: {stats.segments_translated}/{stats.segments_total} "
            f"(rejected: {stats.segments_rejected})"
        )
        print(f"API calls made:  {stats.api_calls}")
        print(f"Output:          {out_path}")
        return 0

    if args.layout_engine == "direct":
        if args.mapping_json:
            raise ValueError("--mapping-json is only supported with --layout-engine html.")
        if not args.target_lang:
            raise ValueError("--target-lang is required with --layout-engine direct.")
        stats = translate_pdf_direct(
            pdf_in=input_path,
            pdf_out=out_path,
            target_lang=args.target_lang,
            source_lang=args.source_lang,
            translate_image_text=args.translate_image_text,
            engine=args.engine,
        )
        print(f"Source language: {stats.source_lang}")
        print(
            f"Blocks translated: {stats.blocks_translated}/{stats.blocks_total} "
            f"(skipped: {stats.blocks_skipped}, retried: {stats.blocks_retried}, rejected: {stats.blocks_rejected})"
        )
        if stats.blocks_truncated or stats.blocks_dropped:
            print(
                f"Layout fit warnings: {stats.blocks_truncated} truncated, "
                f"{stats.blocks_dropped} dropped (translation longer than original box)"
            )
        print(f"API calls made:  {stats.api_calls}")
        if args.translate_image_text:
            print(
                "Image text translated: "
                f"{stats.image_blocks_translated} blocks "
                f"(regions: {stats.image_regions_processed}, rejected: {stats.image_blocks_rejected}, "
                f"API calls: {stats.image_api_calls})"
            )
        print(f"PDF output:      {out_path}")
        return 0

    ensure_chromium_installed()

    page_size = get_first_page_size(input_path)

    html_dir = workdir / "html"
    html_dir.mkdir(parents=True, exist_ok=True)

    # 1) Convert PDF -> HTML
    html_original = convert_pdf_to_html(input_path, html_dir)

    # 2) Replace text in HTML (optional - JSON mapping or LLM translation)
    html_translated = html_dir / (input_path.stem + ".translated.html")
    html_for_pdf = html_original
    stats = None

    # Check for conflicting options
    if args.mapping_json and args.target_lang:
        raise ValueError("Cannot use both --mapping-json and --target-lang. Choose one translation method.")
    if not args.mapping_json and not args.target_lang:
        raise ValueError("--target-lang is required unless --mapping-json is provided.")

    if args.target_lang:
        # LLM-based translation
        print(f"Starting LLM translation to {args.target_lang}...")
        stats = translate_html_content(
            html_original,
            html_translated,
            target_lang=args.target_lang,
            source_lang=args.source_lang,
            engine=args.engine,
        )
        html_for_pdf = html_translated
    elif args.mapping_json:
        # JSON mapping-based replacement
        mapping_json = Path(args.mapping_json).expanduser().resolve()
        if not mapping_json.exists():
            raise FileNotFoundError(f"Mapping JSON not found: {mapping_json}")

        mapping = load_mapping(mapping_json)
        stats = replace_text_nodes(html_original, html_translated, mapping)
        html_for_pdf = html_translated

    # 3) Render HTML -> PDF
    has_text_changes = html_for_pdf != html_original
    render_html_to_pdf(
        html_for_pdf,
        out_path,
        page_size=page_size,
        adjust_text_overflow=has_text_changes,
        hide_background_images=has_text_changes,
    )

    # Optionally save HTML files to output directory
    if args.save_html:
        import shutil
        html_output_dir = out_path.parent / "html"
        html_output_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy original HTML
        html_original_copy = html_output_dir / html_original.name
        shutil.copy2(html_original, html_original_copy)
        print(f"HTML original saved:   {html_original_copy}")
        
        # Copy translated HTML if it exists and is different
        if html_for_pdf != html_original and html_translated.exists():
            html_translated_copy = html_output_dir / html_translated.name
            shutil.copy2(html_translated, html_translated_copy)
            print(f"HTML translated saved: {html_translated_copy}")
    else:
        print(f"HTML original:   {html_original}")
        if args.target_lang and stats is not None:
            print(f"HTML translated: {html_translated}")
    
    if args.target_lang and stats is not None:
        print(f"Source language: {stats.source_lang}")
        print(f"Nodes translated: {stats.nodes_translated} (skipped: {stats.nodes_skipped})")
        print(f"API calls made:  {stats.api_calls}")
    elif stats is not None:
        print(f"Replaced nodes:  {stats.replaced} (skipped: {stats.skipped})")
    else:
        print("No translation applied.")
    print(f"PDF output:      {out_path}")

    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PdfContentPolicyError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
