from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

import cli
from app.pipeline.translate_pdf_direct import DirectTranslationStats

ROOT = Path(__file__).resolve().parent.parent
_BATCH_PATH = ROOT / "scripts" / "translate_input_to_all_eu_languages.py"


def _load_batch_module():
    spec = importlib.util.spec_from_file_location("_eu_batch", _BATCH_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    # Register before exec so dataclasses defined in the module can resolve their
    # own __module__ during class creation.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class _PlainStats:
    segments_translated: int
    segments_total: int
    segments_rejected: int
    source_lang: str
    api_calls: int


class WriteStatsJsonTests(unittest.TestCase):
    def test_serializes_dataclass_stats_with_kind(self) -> None:
        stats = DirectTranslationStats(
            blocks_total=10,
            blocks_translated=9,
            blocks_skipped=1,
            blocks_retried=0,
            blocks_rejected=0,
            api_calls=10,
            source_lang="en",
            blocks_residual_source=2,
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "nested" / "stats.json"
            cli.write_stats_json(str(out), stats, kind="pdf_direct")
            payload = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(payload["stats_kind"], "pdf_direct")
        self.assertEqual(payload["blocks_residual_source"], 2)
        self.assertEqual(payload["blocks_translated"], 9)

    def test_none_path_and_none_stats_are_noops(self) -> None:
        # Must not raise; simply writes nothing.
        cli.write_stats_json(None, _PlainStats(1, 1, 0, "en", 1), kind="txt")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "stats.json"
            cli.write_stats_json(str(out), None, kind="pdf_direct")
            self.assertFalse(out.exists())


class ReadStatsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.batch = _load_batch_module()

    def test_missing_or_invalid_file_returns_no_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "absent.json"
            self.assertEqual(self.batch.read_stats(missing), (None, []))
            bad = Path(tmp) / "bad.json"
            bad.write_text("not json", encoding="utf-8")
            self.assertEqual(self.batch.read_stats(bad), (None, []))

    def test_derives_quality_flags_from_nonzero_defect_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stats.json"
            path.write_text(
                json.dumps(
                    {
                        "blocks_residual_source": 3,
                        "blocks_unplaced": 1,
                        "blocks_rejected": 0,
                        "image_blocks_rejected": 2,
                    }
                ),
                encoding="utf-8",
            )
            stats, flags = self.batch.read_stats(path)

        self.assertEqual(stats["blocks_residual_source"], 3)
        self.assertIn("residual_source_text", flags)
        self.assertIn("unplaced_blocks", flags)
        self.assertIn("rejected_image_blocks", flags)
        self.assertNotIn("rejected_blocks", flags)

    def test_clean_run_has_no_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stats.json"
            path.write_text(
                json.dumps({"blocks_residual_source": 0, "blocks_unplaced": 0}),
                encoding="utf-8",
            )
            _, flags = self.batch.read_stats(path)
        self.assertEqual(flags, [])


if __name__ == "__main__":
    unittest.main()
