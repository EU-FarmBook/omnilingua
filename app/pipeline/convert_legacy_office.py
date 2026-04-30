from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _resolve_soffice_binary() -> str | None:
    for candidate in ("soffice", "libreoffice"):
        binary = shutil.which(candidate)
        if binary:
            return binary
    return None


def convert_legacy_office_document(input_path: Path, *, output_suffix: str, output_dir: Path) -> Path:
    soffice = _resolve_soffice_binary()
    if not soffice:
        raise RuntimeError(
            f"Conversion for '{input_path.suffix}' requires LibreOffice/soffice to be installed."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    convert_format = output_suffix.lstrip(".")
    proc = subprocess.run(
        [
            soffice,
            "--headless",
            "--convert-to",
            convert_format,
            "--outdir",
            str(output_dir),
            str(input_path),
        ],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"LibreOffice conversion failed for {input_path.name}: {proc.stderr or proc.stdout}"
        )

    converted = output_dir / f"{input_path.stem}{output_suffix}"
    if not converted.exists():
        raise RuntimeError(f"Converted file not found after LibreOffice conversion: {converted}")
    return converted
