from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "translate_input_to_all_eu_languages.py"


class BulkEuTranslationRunnerTests(unittest.TestCase):
    def test_source_language_artifact_is_copied_and_manifested(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            input_dir = tmp / "input"
            output_dir = tmp / "output"
            input_dir.mkdir()
            source = input_dir / "sample.txt"
            source.write_text("Hello from the source document.", encoding="utf-8")

            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input-dir",
                    str(input_dir),
                    "--output-dir",
                    str(output_dir),
                    "--source-lang",
                    "en",
                    "--languages",
                    "en",
                    "--python-bin",
                    sys.executable,
                ],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            copied = output_dir / "en" / "sample_en.txt"
            self.assertEqual(copied.read_text(encoding="utf-8"), source.read_text(encoding="utf-8"))

            manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["results"][0]["status"], "copied_source_language")
            self.assertEqual(manifest["results"][0]["target_lang"], "en")


if __name__ == "__main__":
    unittest.main()
