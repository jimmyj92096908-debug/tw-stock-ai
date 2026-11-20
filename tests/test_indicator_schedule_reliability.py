"""Protect the independent catch-up/score automation wiring.

These tests validate routing and write bounds, not live production execution.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
IND = ROOT / ".github/workflows/daily-indicator-catchup.yml"
SCORE = ROOT / ".github/workflows/composite-after-market-refresh.yml"


class IndicatorScheduleReliabilityTests(unittest.TestCase):
    def test_fallback_has_scheduled_and_upstream_modes(self):
        source = IND.read_text(encoding="utf-8")
        self.assertIn('cron: "10 19 * * 1-5"', source)
        self.assertIn("workflow_run:", source)
        self.assertIn("github.event_name == 'schedule'", source)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", source)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", source)
        self.assertIn("cancel-in-progress: false", source)

    def test_indicator_write_remains_bounded_and_guarded(self):
        source = IND.read_text(encoding="utf-8")
        self.assertIn("--per-market 20", source)
        self.assertIn("STOCK_INDICATOR_CATCHUP_WRITE_ENABLED", source)
        self.assertIn("STOCK_INDICATOR_CATCHUP_WRITE_ENABLED: \"yes\"", source)
        self.assertIn("--apply --per-market 20", source)

    def test_score_rebuild_accepts_scheduled_indicator_success(self):
        source = SCORE.read_text(encoding="utf-8")
        self.assertIn("Verified History Indicator Catch-Up", source)
        self.assertIn("github.event.workflow_run.event == 'schedule'", source)
        self.assertIn("github.event.workflow_run.event == 'workflow_run'", source)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", source)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", source)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.apply == true", source)


if __name__ == "__main__":
    unittest.main()
