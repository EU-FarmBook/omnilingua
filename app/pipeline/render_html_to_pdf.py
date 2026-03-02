# render_html_to_pdf.py

from __future__ import annotations

import asyncio

from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from app.pipeline.pdf_page_size import PageSize


def pt_to_in(pt: float) -> float:
    # 1 inch = 72 points
    return pt / 72.0


async def _fit_overflowing_absolute_text(page) -> int:
    """
    Shrink overflowing absolute text boxes instead of letting them wrap and overlap.
    Returns number of adjusted elements.
    """
    return await page.evaluate(
        """() => {
        let adjusted = 0;
        const pages = Array.from(document.querySelectorAll('div[id^="page"][id$="-div"]'));

        for (const pageDiv of pages) {
            const pageWidth = pageDiv.offsetWidth || 892;
            const nodes = Array.from(pageDiv.querySelectorAll('p, span, b, i, font, a'));

            for (const node of nodes) {
                const text = (node.textContent || '').trim();
                if (!text) continue;

                const style = getComputedStyle(node);
                if (style.position !== 'absolute') continue;

                const left = parseFloat(style.left || node.style.left || '0') || 0;
                const maxWidth = Math.max(60, pageWidth - left - 20);
                node.style.maxWidth = `${maxWidth}px`;
                node.style.whiteSpace = 'nowrap';
                node.style.overflowWrap = 'normal';
                node.style.wordBreak = 'normal';

                if (node.scrollWidth <= maxWidth + 1) continue;

                const originalFontSize = parseFloat(style.fontSize || '0');
                if (!Number.isFinite(originalFontSize) || originalFontSize <= 0) continue;

                const minFontSize = Math.max(8, originalFontSize * 0.72);
                let size = originalFontSize;

                while (size > minFontSize && node.scrollWidth > maxWidth + 1) {
                    size -= 0.25;
                    node.style.fontSize = `${size.toFixed(2)}px`;
                }

                if (node.scrollWidth > maxWidth + 1) {
                    const squeeze = Math.max(0.85, maxWidth / node.scrollWidth);
                    if (squeeze < 0.999) {
                        node.style.transformOrigin = 'left top';
                        node.style.transform = `scaleX(${squeeze.toFixed(4)})`;
                    }
                }

                adjusted += 1;
            }
        }

        return adjusted;
    }"""
    )


async def _render_with_chromium(
    html_path: Path,
    pdf_path: Path,
    page_size: PageSize,
    adjust_text_overflow: bool = False,
    hide_background_images: bool = False,
) -> None:
    """
    Render HTML to PDF using headless Chromium, matching the source PDF page size.
    
    Fixes applied:
    - Remove prefer_css_page_size (was conflicting with explicit dimensions)
    - Override body background to white (remove gray background from pdftohtml)
    - Scale content properly to fit page
    """
    html_path = html_path.resolve()
    pdf_path = pdf_path.resolve()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    margins: Any = {"top": "0", "right": "0", "bottom": "0", "left": "0"}
    
    width_in = pt_to_in(page_size.width_pt)
    height_in = pt_to_in(page_size.height_pt)
    
    # pdftohtml generates HTML with pixel dimensions (usually at 96 DPI or similar)
    # The width/height in the HTML is in pixels (e.g., 892px for A4 at ~120 DPI)
    # We need to scale the content to fit the PDF page size
    pdf_width_pt = page_size.width_pt
    pdf_height_pt = page_size.height_pt

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        
        # Don't set viewport - let it be determined by the content
        page = await browser.new_page()

        await page.goto(html_path.as_uri(), wait_until="networkidle")
        
        # Get the actual content dimensions from the first page div
        content_dims = await page.evaluate("""() => {
            const pageDiv = document.querySelector('[id^="page1-div"]');
            if (pageDiv) {
                return {
                    width: pageDiv.offsetWidth,
                    height: pageDiv.offsetHeight
                };
            }
            // Fallback to body
            return {
                width: document.body.offsetWidth,
                height: document.body.offsetHeight
            };
        }""")
        
        content_width_px = content_dims.get('width', 892)
        content_height_px = content_dims.get('height', 1262)

        # Chromium lays out HTML in CSS px (effectively 96 px per inch).
        # The PDF page dimensions are specified in inches (via width/height),
        # so compute how many CSS px correspond to that physical page.
        PDF_PT_PER_IN = 72.0
        CSS_PX_PER_IN = 96.0  # Chromium’s CSS pixel reference

        page_width_in = pdf_width_pt / PDF_PT_PER_IN
        page_height_in = pdf_height_pt / PDF_PT_PER_IN

        page_width_css_px = page_width_in * CSS_PX_PER_IN
        page_height_css_px = page_height_in * CSS_PX_PER_IN

        scale_x = page_width_css_px / content_width_px if content_width_px > 0 else 1.0
        scale_y = page_height_css_px / content_height_px if content_height_px > 0 else 1.0

        # Use smaller scale so it fits both width & height
        scale = min(scale_x, scale_y)

        print(f"  Page (in): {page_width_in:.3f} x {page_height_in:.3f}")
        print(f"  Page (css px @96dpi): {page_width_css_px:.1f} x {page_height_css_px:.1f}")
        
        print(f"  Content size: {content_width_px}px x {content_height_px}px")
        print(f"  PDF size: {pdf_width_pt:.1f}pt x {pdf_height_pt:.1f}pt")
        print(f"  Scale factor: {scale:.4f}")

        # Inject print CSS to:
        #  - force white background
        #  - remove margins
        #  - force each page div onto its own PDF page
        #  - prevent text overflow issues
        fix_css = """
        <style>
          @page { 
            margin: 0; 
            size: "" + str(width_in) + ""in "" + str(height_in) + ""in;
          }

          html, body {
            margin: 0 !important;
            padding: 0 !important;
            background: #fff !important;
            overflow: hidden !important;
          }

          /* kill pdftohtml's grey background attribute */
          body[bgcolor] { background: #fff !important; }

          /* Ensure each page div prints on its own page */
          div[id^="page"][id$="-div"] {
            break-after: page;
            page-break-after: always;
            overflow: hidden !important;
            position: relative !important;
          }

          /* Hide anchor markers inserted by pdftohtml */
          a[name] { display: none !important; }
          
          /* Ensure images don't overflow */
          img { max-width: 100% !important; }
          
          /* Keep pdftohtml's fixed-layout behavior for absolute text boxes. */
          p, span, b, i, font, a { 
            white-space: nowrap !important;
          }
        </style>
        """

        await page.add_style_tag(content=fix_css)

        if hide_background_images:
            # pdftohtml page PNGs often contain the original page text rasterized.
            # Hide them for translated output to avoid source-text ghosting beneath translated text.
            await page.add_style_tag(
                content="""
                div[id^="page"][id$="-div"] > img[alt="background image"] {
                  display: none !important;
                }
                """
            )

        if adjust_text_overflow:
            adjusted = await _fit_overflowing_absolute_text(page)
            print(f"  Overflow text boxes adjusted: {adjusted}")

        # Use print media rules consistently
        await page.emulate_media(media="print")

        # Small delay to let CSS apply
        await page.wait_for_timeout(200)

        await page.pdf(
            path=str(pdf_path),
            print_background=True,
            prefer_css_page_size=False,
            width=f"{width_in:.4f}in",
            height=f"{height_in:.4f}in",
            margin=margins,
            scale=scale,
        )

        await browser.close()


def render_html_to_pdf(
    html_path: Path,
    pdf_path: Path,
    page_size: PageSize,
    adjust_text_overflow: bool = False,
    hide_background_images: bool = False,
) -> None:
    """
    Synchronous wrapper.
    """
    asyncio.run(
        _render_with_chromium(
            html_path,
            pdf_path,
            page_size,
            adjust_text_overflow=adjust_text_overflow,
            hide_background_images=hide_background_images,
        )
    )
