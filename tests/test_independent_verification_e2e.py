"""Real CLI end-to-end acceptance of the offline, fail-closed model path.

No mocks: spawn the entry point as an external process and inspect its artifact.
This is a research-only E2E test, not a production Neon or LINE acceptance test.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMMAND = ROOT / "scripts" / "investment_model_pipeline.py"
MODEL = ROOT / "models" / "tw-factor-ridge-1-research.json"


def offline_cli(*args):
    # Defense in depth: running these tests cannot inherit production secrets.
    env = {
        key: value for key, value in os.environ.items()
        if key not in {
            "DATABASE_URL", "NEON_API_KEY", "LINE_CHANNEL_ACCESS_TOKEN",
            "LINE_CHANNEL_SECRET", "INVESTMENT_MODEL_READONLY",
            "PYTHONPATH",
        }
    }
    # Exercise the documented CLI from a clean shell, no special import path.
    return subprocess.run(
        [sys.executable, str(COMMAND), *map(str, args)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=45,
        check=False,
    )


class OfflineResearchEndToEnd(unittest.TestCase):
    def test_real_entrypoint_runs_twice_with_identical_research_evidence(self):
        with TemporaryDirectory() as directory:
            first = Path(directory) / "first.json"
            second = Path(directory) / "second.json"
            for target in (first, second):
                run = offline_cli("--output", target)
                self.assertEqual(run.returncode, 0, msg=run.stderr[-1200:])
                self.assertTrue(target.is_file())
            one = json.loads(first.read_text(encoding="utf-8"))
            two = json.loads(second.read_text(encoding="utf-8"))
            # Midnight is not a correctness dependency of model outputs.
            one.pop("report_generated_taipei_date", None)
            two.pop("report_generated_taipei_date", None)
            self.assertEqual(one, two)
            self.assertEqual(one["data_mode"], "offline_committed_evidence_only")
            self.assertTrue(one["offline_stock_data_is_not_live"])
            self.assertEqual(one["ranking"]["stocks"], [])
            self.assertTrue(one["abstain_from_trading"])
            self.assertFalse(one["publish_line_trade_signal"])
            self.assertFalse(one["orders_enabled"])
            self.assertEqual(one["model"]["research_evidence_status"],
                             "INCOMPLETE_OR_FAILED")
            self.assertLess(one["model"]["holdout_net_excess"], 0)

    def test_tampered_training_evidence_never_enables_trading(self):
        with TemporaryDirectory() as directory:
            changed = json.loads(MODEL.read_text(encoding="utf-8"))
            changed["may_send_trade_signals"] = True
            changed["production_release_approved"] = True
            changed_path = Path(directory) / "modified-evidence.json"
            changed_path.write_text(json.dumps(changed), encoding="utf-8")
            out = Path(directory) / "tampered-report.json"
            run = offline_cli("--model-in", changed_path, "--output", out)
            self.assertEqual(run.returncode, 0, msg=run.stderr[-1200:])
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(report["model"]["research_evidence_status"],
                             "INCOMPLETE_OR_FAILED")
            self.assertFalse(report["publish_line_trade_signal"])
            self.assertFalse(report["orders_enabled"])
            self.assertTrue(report["abstain_from_trading"])

    def test_missing_model_evidence_fails_without_artifact(self):
        with TemporaryDirectory() as directory:
            missing = Path(directory) / "missing-model.json"
            out = Path(directory) / "should-not-exist.json"
            run = offline_cli("--model-in", missing, "--output", out)
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
