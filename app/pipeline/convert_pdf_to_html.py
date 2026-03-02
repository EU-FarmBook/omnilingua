# convert_pdf_to_html.py

from __future__ import annotations

import subprocess

from pathlib import Path


def convert_pdf_to_html(pdf_path: Path, out_dir: Path) -> Path:
    """
    Convert a born-digital PDF to HTML using Poppler's `pdftohtml`.

    We aim for layout preservation by using:
      -c        : generate complex output that tries to preserve positions
      -s        : generate a single HTML page (not one file per page in frames)
      -noframes : avoid frames output

    Returns: path to the generated HTML file.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # pdftohtml writes output based on an output "base name". If you pass a .html file,
    # it will often generate additional assets alongside it.
    html_path = out_dir / (pdf_path.stem + ".html")

    cmd = [
        "pdftohtml",
        "-c",
        "-s",
        "-noframes",
        str(pdf_path),
        str(html_path),
    ]

    # Capture stdout/stderr for debugging if needed.
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "pdftohtml failed.\n"
            f"Command: {' '.join(cmd)}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}\n"
        )

    if not html_path.exists():
        # Some builds output <base>.html without respecting the given extension;
        # fallback to searching for generated HTML in out_dir.
        candidates = sorted(out_dir.glob(pdf_path.stem + "*.html"))
        if candidates:
            return candidates[0]
        raise FileNotFoundError(f"Expected HTML not found at {html_path}")

    return html_path
