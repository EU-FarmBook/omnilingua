# cli.py

from __future__ import annotations

import argparse
from pathlib import Path

from app.pipeline.convert_pdf_to_html import convert_pdf_to_html
from app.pipeline.replace_html_text import load_mapping, replace_text_nodes
from app.pipeline.render_html_to_pdf import render_html_to_pdf
from app.pipeline.pdf_page_size import get_first_page_size
from app.pipeline.translator_llm import translate_html_content
from app.pipeline.translate_pdf_direct import translate_pdf_direct


def resolve_pdf_out_path(
    pdf_out_arg: str,
    pdf_in: Path,
    target_lang: str | None,
    mapping_json: str | None,
) -> Path:
    """
    Resolve --pdf-out as either:
    - explicit PDF filepath, or
    - output directory (auto-name based on input + suffix).
    """
    raw = Path(pdf_out_arg).expanduser()
    out_path = raw.resolve()

    is_dir_like = raw.as_posix().endswith("/") or out_path.is_dir() or out_path.suffix.lower() != ".pdf"
    if not is_dir_like:
        return out_path

    suffix = target_lang if target_lang else ("mapped" if mapping_json else "out")
    return out_path / f"{pdf_in.stem}_{suffix}.pdf"


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
    ap = argparse.ArgumentParser(description="PDF translator with LLM support.")
    ap.add_argument("--pdf-in", required=True, help="Input PDF path (born-digital).")
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
        help="Output PDF file path, or output directory (auto-names as <input_stem>_<target_lang>.pdf).",
    )
    ap.add_argument("--save-html", action="store_true",
                    help="Also save intermediate HTML files to the output directory.")
    ap.add_argument(
        "--layout-engine",
        choices=("html", "direct"),
        default="html",
        help="Pipeline engine: 'html' (pdftohtml round-trip) or 'direct' (PDF block rewrite).",
    )
    args = ap.parse_args()

    pdf_in = Path(args.pdf_in).expanduser().resolve()
    workdir = Path(args.workdir).expanduser().resolve()
    pdf_out = resolve_pdf_out_path(
        args.pdf_out,
        pdf_in=pdf_in,
        target_lang=args.target_lang,
        mapping_json=args.mapping_json,
    )

    if not pdf_in.exists():
        raise FileNotFoundError(f"Input PDF not found: {pdf_in}")

    if args.layout_engine == "direct":
        if args.mapping_json:
            raise ValueError("--mapping-json is only supported with --layout-engine html.")
        if not args.target_lang:
            raise ValueError("--target-lang is required with --layout-engine direct.")
        stats = translate_pdf_direct(
            pdf_in=pdf_in,
            pdf_out=pdf_out,
            target_lang=args.target_lang,
            source_lang=args.source_lang,
        )
        print(f"Source language: {stats.source_lang}")
        print(
            f"Blocks translated: {stats.blocks_translated}/{stats.blocks_total} "
            f"(skipped: {stats.blocks_skipped}, retried: {stats.blocks_retried}, rejected: {stats.blocks_rejected})"
        )
        print(f"API calls made:  {stats.api_calls}")
        print(f"PDF output:      {pdf_out}")
        return 0

    page_size = get_first_page_size(pdf_in)

    html_dir = workdir / "html"
    html_dir.mkdir(parents=True, exist_ok=True)

    # 1) Convert PDF -> HTML
    html_original = convert_pdf_to_html(pdf_in, html_dir)

    # 2) Replace text in HTML (optional - JSON mapping or LLM translation)
    html_translated = html_dir / (pdf_in.stem + ".translated.html")
    html_for_pdf = html_original
    stats = None

    # Check for conflicting options
    if args.mapping_json and args.target_lang:
        raise ValueError("Cannot use both --mapping-json and --target-lang. Choose one translation method.")

    if args.target_lang:
        # LLM-based translation
        print(f"Starting LLM translation to {args.target_lang}...")
        stats = translate_html_content(
            html_original,
            html_translated,
            target_lang=args.target_lang,
            source_lang=args.source_lang
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
        pdf_out,
        page_size=page_size,
        adjust_text_overflow=has_text_changes,
        hide_background_images=has_text_changes,
    )

    # Optionally save HTML files to output directory
    if args.save_html:
        import shutil
        html_output_dir = pdf_out.parent / "html"
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
    print(f"PDF output:      {pdf_out}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
