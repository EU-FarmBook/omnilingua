from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = ROOT / "tests" / "integration_cases.json"
DEFAULT_WORK_ROOT = ROOT / "work" / "regression"
PYTHON_BIN = ROOT / ".venv" / "bin" / "python"

TOKEN_SETS = {
    "dutch_basic": {"de", "het", "een", "van", "voor", "met", "onder", "inleiding", "sleutelwoorden"},
}


@dataclass
class CaseResult:
    name: str
    success: bool
    reasons: list[str]
    artifact_dir: Path


def load_cases() -> list[dict[str, Any]]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def run_command(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)


def pdf_page_count(pdf_path: Path) -> int:
    proc = run_command(["pdfinfo", str(pdf_path)], cwd=ROOT)
    if proc.returncode != 0:
        raise RuntimeError(f"pdfinfo failed for {pdf_path}:\n{proc.stderr}")
    match = re.search(r"^Pages:\s+(\d+)$", proc.stdout, re.MULTILINE)
    if not match:
        raise RuntimeError(f"Could not parse page count for {pdf_path}")
    return int(match.group(1))


def pdf_text(pdf_path: Path) -> str:
    proc = run_command(["pdftotext", str(pdf_path), "-"], cwd=ROOT)
    if proc.returncode != 0:
        raise RuntimeError(f"pdftotext failed for {pdf_path}:\n{proc.stderr}")
    return proc.stdout


def count_greek_chars(text: str) -> int:
    return sum(1 for ch in text if 0x0370 <= ord(ch) <= 0x03FF)


def token_hits(text: str, token_set_name: str) -> int:
    tokens = TOKEN_SETS[token_set_name]
    lowered = re.findall(r"\b[\w-]+\b", text.lower())
    return sum(1 for token in lowered if token in tokens)


def run_case(case: dict[str, Any], *, work_root: Path) -> CaseResult:
    name = case["name"]
    artifact_dir = work_root / name
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    pdf_in = ROOT / case["pdf_in"]
    out_dir = artifact_dir / "output"
    work_dir = artifact_dir / "workdir"
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(PYTHON_BIN),
        "cli.py",
        "--pdf-in",
        str(pdf_in),
        "--workdir",
        str(work_dir),
        "--target-lang",
        case["target_lang"],
        "--layout-engine",
        case["layout_engine"],
        "--pdf-out",
        str(out_dir) + "/",
    ]
    if case.get("source_lang"):
        cmd.extend(["--source-lang", case["source_lang"]])
    if case.get("translate_image_text"):
        cmd.append("--translate-image-text")

    proc = run_command(cmd, cwd=ROOT)
    (artifact_dir / "stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (artifact_dir / "stderr.txt").write_text(proc.stderr, encoding="utf-8")

    reasons: list[str] = []
    if proc.returncode != 0:
        reasons.append(f"CLI failed with exit code {proc.returncode}")
        return CaseResult(name=name, success=False, reasons=reasons, artifact_dir=artifact_dir)

    output_candidates = sorted(out_dir.glob("*.pdf"))
    if len(output_candidates) != 1:
        reasons.append(f"Expected exactly 1 output PDF, found {len(output_candidates)}")
        return CaseResult(name=name, success=False, reasons=reasons, artifact_dir=artifact_dir)

    pdf_out = output_candidates[0]
    expect = case["expect"]

    try:
        if expect.get("same_page_count"):
            in_pages = pdf_page_count(pdf_in)
            out_pages = pdf_page_count(pdf_out)
            if in_pages != out_pages:
                reasons.append(f"Page count mismatch: input={in_pages}, output={out_pages}")

        output_text = pdf_text(pdf_out)
        (artifact_dir / "output.txt").write_text(output_text, encoding="utf-8")

        min_text_chars = expect.get("min_text_chars")
        if min_text_chars is not None and len(output_text.strip()) < min_text_chars:
            reasons.append(
                f"Translated text too short: got {len(output_text.strip())}, expected at least {min_text_chars}"
            )

        if expect.get("script") == "greek":
            greek_chars = count_greek_chars(output_text)
            if greek_chars < int(expect.get("min_script_chars", 1)):
                reasons.append(
                    f"Too few Greek characters: got {greek_chars}, expected at least {expect['min_script_chars']}"
                )

        token_set_name = expect.get("token_set")
        if token_set_name:
            hits = token_hits(output_text, token_set_name)
            if hits < int(expect.get("min_token_hits", 1)):
                reasons.append(
                    f"Too few token hits for {token_set_name}: got {hits}, expected at least {expect['min_token_hits']}"
                )
    except Exception as exc:
        reasons.append(str(exc))

    return CaseResult(name=name, success=not reasons, reasons=reasons, artifact_dir=artifact_dir)


def main() -> int:
    if not PYTHON_BIN.exists():
        print(f"Virtualenv Python not found: {PYTHON_BIN}", file=sys.stderr)
        return 2

    work_root = DEFAULT_WORK_ROOT
    work_root.mkdir(parents=True, exist_ok=True)
    cases = load_cases()
    results = [run_case(case, work_root=work_root) for case in cases]

    failures = [result for result in results if not result.success]
    for result in results:
        status = "PASS" if result.success else "FAIL"
        print(f"[{status}] {result.name} -> {result.artifact_dir}")
        for reason in result.reasons:
            print(f"  - {reason}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
