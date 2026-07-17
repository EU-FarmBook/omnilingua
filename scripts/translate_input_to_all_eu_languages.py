#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.engines import validate_engine

SUPPORTED_EXTENSIONS = frozenset({".pdf", ".txt", ".doc", ".docx", ".ppt", ".pptx"})
EU_LANGUAGE_CODES = (
    "bg",
    "cs",
    "da",
    "de",
    "el",
    "en",
    "es",
    "et",
    "fi",
    "fr",
    "ga",
    "hr",
    "hu",
    "it",
    "lt",
    "lv",
    "mt",
    "nl",
    "pl",
    "pt",
    "ro",
    "sk",
    "sl",
    "sv",
)


@dataclass
class JobResult:
    input_path: str
    target_lang: str
    output_path: str
    status: str
    returncode: int | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    reason: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Translate every supported document in input/ into all 24 official EU "
            "languages using the project CLI."
        )
    )
    parser.add_argument("--input-dir", default="input", help="Directory containing source documents.")
    parser.add_argument(
        "--output-dir",
        default="output/eu_translations",
        help="Directory where translated files, logs, and manifest are written.",
    )
    parser.add_argument(
        "--workdir",
        default=None,
        help="Working directory for intermediate files. Defaults to <output-dir>/_work.",
    )
    parser.add_argument(
        "--source-lang",
        default=None,
        help=(
            "Source language for all input files. When omitted, each pipeline "
            "auto-detects the source language per file (recommended for mixed or "
            "non-English input sets). Declaring a wrong source language silently "
            "mistranslates every non-matching document, so only set this when the "
            "whole input set is known to share one language."
        ),
    )
    parser.add_argument(
        "--auto-source",
        action="store_true",
        help=(
            "Force per-file auto-detection even if --source-lang is given. "
            "(Auto-detection is already the default when --source-lang is omitted.)"
        ),
    )
    parser.add_argument(
        "--engine",
        choices=("llm", "deepl", "adaptive"),
        default=os.getenv("ENGINE"),
        help=(
            "Translation backend. Defaults to ENGINE env var if set, otherwise the CLI's "
            "TRANSLATION_ENGINE/default behavior."
        ),
    )
    parser.add_argument(
        "--languages",
        nargs="+",
        default=list(EU_LANGUAGE_CODES),
        help="Target language codes to generate. Defaults to all 24 EU languages.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-run jobs even if the expected output file already exists.",
    )
    parser.add_argument(
        "--no-copy-source-language",
        action="store_true",
        help=(
            "Do not copy the input file for target_lang == source_lang. By default, this "
            "creates the source-language artifact so every input has 24 outputs."
        ),
    )
    parser.add_argument(
        "--python-bin",
        default=os.getenv("PYTHON_BIN") or str(ROOT / ".venv" / "bin" / "python"),
        help="Python interpreter used to run cli.py.",
    )
    return parser.parse_args()


def resolve(path_value: str) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def output_suffix(input_path: Path) -> str:
    suffix = input_path.suffix.lower()
    if suffix == ".doc":
        return ".docx"
    if suffix == ".ppt":
        return ".pptx"
    return suffix


def discover_inputs(input_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def run_command(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def elapsed_seconds(started: float) -> float:
    return round(time.monotonic() - started, 3)


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remainder = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {remainder:.1f}s"
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)}h {int(minutes)}m {remainder:.1f}s"


def write_manifest(output_dir: Path, results: list[JobResult]) -> None:
    manifest = {
        "generated_at": utc_now(),
        "results": [asdict(result) for result in results],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> int:
    args = parse_args()
    input_dir = resolve(args.input_dir)
    output_dir = resolve(args.output_dir)
    work_root = resolve(args.workdir) if args.workdir else output_dir / "_work"
    logs_root = output_dir / "_logs"
    python_bin = Path(args.python_bin).expanduser()
    if not python_bin.is_absolute():
        python_bin = (ROOT / python_bin).resolve()

    if not input_dir.exists():
        print(f"Input directory does not exist: {input_dir}", file=sys.stderr)
        return 2
    if not python_bin.exists():
        print(f"Python interpreter does not exist: {python_bin}", file=sys.stderr)
        return 2

    languages = [lang.strip().lower() for lang in args.languages if lang.strip()]
    invalid = sorted(set(languages) - set(EU_LANGUAGE_CODES))
    if invalid:
        print(f"Unsupported language code(s): {', '.join(invalid)}", file=sys.stderr)
        return 2

    inputs = discover_inputs(input_dir)
    if not inputs:
        print(f"No supported input files found in {input_dir}", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)
    logs_root.mkdir(parents=True, exist_ok=True)

    source_lang = None if args.auto_source else ((args.source_lang or "").strip().lower() or None)
    effective_engine = validate_engine(args.engine)
    total = len(inputs) * len(languages)
    results: list[JobResult] = []
    failures = 0
    job_index = 0
    run_started_at = utc_now()
    run_started = time.monotonic()

    print(f"Input directory:  {input_dir}")
    print(f"Output directory: {output_dir}")
    print(f"Work directory:   {work_root}")
    print(f"Files:            {len(inputs)}")
    print(f"Languages:        {len(languages)}")
    print(f"Jobs:             {total}")
    print(f"Engine:           {effective_engine}")
    print(f"Started at:       {run_started_at}")

    for input_path in inputs:
        desired_suffix = output_suffix(input_path)
        for target_lang in languages:
            job_index += 1
            lang_dir = output_dir / target_lang
            lang_dir.mkdir(parents=True, exist_ok=True)
            output_path = lang_dir / f"{input_path.stem}_{target_lang}{desired_suffix}"
            log_prefix = f"{input_path.stem}_{target_lang}"
            stdout_path = logs_root / f"{log_prefix}.stdout.txt"
            stderr_path = logs_root / f"{log_prefix}.stderr.txt"

            job_started_at = utc_now()
            job_started = time.monotonic()
            print(f"[{job_index}/{total}] {input_path.name} -> {target_lang} started {job_started_at}", flush=True)

            if output_path.exists() and not args.overwrite:
                duration = elapsed_seconds(job_started)
                print(f"  skipped existing in {format_duration(duration)}")
                results.append(
                    JobResult(
                        input_path=display_path(input_path),
                        target_lang=target_lang,
                        output_path=display_path(output_path),
                        status="skipped_existing",
                        started_at=job_started_at,
                        finished_at=utc_now(),
                        duration_seconds=duration,
                    )
                )
                continue

            if source_lang and target_lang == source_lang and not args.no_copy_source_language:
                if input_path.suffix.lower() in {".doc", ".ppt"}:
                    reason = (
                        "source-language copy skipped for legacy Office input because translated "
                        "outputs use the converted OOXML extension"
                    )
                    duration = elapsed_seconds(job_started)
                    results.append(
                        JobResult(
                            input_path=display_path(input_path),
                            target_lang=target_lang,
                            output_path=display_path(output_path),
                            status="skipped_same_language",
                            reason=reason,
                            started_at=job_started_at,
                            finished_at=utc_now(),
                            duration_seconds=duration,
                        )
                    )
                    print(f"  skipped: {reason} in {format_duration(duration)}")
                    continue
                shutil.copy2(input_path, output_path)
                duration = elapsed_seconds(job_started)
                print(f"  copied source-language artifact in {format_duration(duration)}")
                results.append(
                    JobResult(
                        input_path=display_path(input_path),
                        target_lang=target_lang,
                        output_path=display_path(output_path),
                        status="copied_source_language",
                        started_at=job_started_at,
                        finished_at=utc_now(),
                        duration_seconds=duration,
                    )
                )
                continue

            job_workdir = work_root / input_path.stem / target_lang
            job_workdir.mkdir(parents=True, exist_ok=True)
            cmd = [
                str(python_bin),
                "cli.py",
                "--document-in",
                str(input_path),
                "--workdir",
                str(job_workdir),
                "--target-lang",
                target_lang,
                "--pdf-out",
                str(lang_dir) + "/",
            ]
            if source_lang:
                cmd.extend(["--source-lang", source_lang])
            if args.engine:
                cmd.extend(["--engine", args.engine])

            proc = run_command(cmd, cwd=ROOT)
            duration = elapsed_seconds(job_started)
            finished_at = utc_now()
            stdout_path.write_text(proc.stdout, encoding="utf-8")
            stderr_path.write_text(proc.stderr, encoding="utf-8")

            if proc.returncode == 0 and output_path.exists():
                status = "translated"
                reason = None
                print(f"  finished {finished_at} in {format_duration(duration)}")
            elif (
                "Source and target language are the same" in proc.stderr
                and not args.no_copy_source_language
                and input_path.suffix.lower() not in {".doc", ".ppt"}
            ):
                # Auto-detection resolved the document's own language as the
                # target: the original *is* the artifact for this language.
                shutil.copy2(input_path, output_path)
                status = "copied_source_language"
                reason = "auto-detected source language equals target"
                print(f"  copied source-language artifact (auto-detected) in {format_duration(duration)}")
            else:
                failures += 1
                status = "failed"
                reason = f"exit_code={proc.returncode}"
                print(
                    f"  failed {finished_at} after {format_duration(duration)}: "
                    f"{reason} (see {display_path(stderr_path)})",
                    flush=True,
                )

            results.append(
                JobResult(
                    input_path=display_path(input_path),
                    target_lang=target_lang,
                    output_path=display_path(output_path),
                    status=status,
                    returncode=proc.returncode,
                    stdout_path=display_path(stdout_path),
                    stderr_path=display_path(stderr_path),
                    reason=reason,
                    started_at=job_started_at,
                    finished_at=finished_at,
                    duration_seconds=duration,
                )
            )
            write_manifest(output_dir, results)

    write_manifest(output_dir, results)
    translated = sum(1 for result in results if result.status == "translated")
    copied = sum(1 for result in results if result.status == "copied_source_language")
    skipped = sum(1 for result in results if result.status.startswith("skipped"))
    failed = sum(1 for result in results if result.status == "failed")
    print("")
    print("Summary")
    print(f"  translated: {translated}")
    print(f"  copied:     {copied}")
    print(f"  skipped:    {skipped}")
    run_finished_at = utc_now()
    run_duration = elapsed_seconds(run_started)
    print(f"  failed:     {failed}")
    print(f"  started:    {run_started_at}")
    print(f"  finished:   {run_finished_at}")
    print(f"  duration:   {format_duration(run_duration)}")
    print(f"  manifest:   {display_path(output_dir / 'manifest.json')}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
