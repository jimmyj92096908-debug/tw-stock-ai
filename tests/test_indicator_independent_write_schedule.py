"""Review contracts for proposed WRITE-enabled independent indicator cron.

The workflow is deliberately only on a review branch: this test does NOT
authorize enabling the new production database write schedule.
"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
IND = ROOT / ".github/workflows/daily-indicator-catchup.yml"
SCORE = ROOT / ".github/workflows/composite-after-market-refresh.yml"


class ProposedIndependentIndicatorScheduleTests(unittest.TestCase):
    def test_only_one_scheduled_source_per_day_without_workflow_run_duplication(self):
        source = IND.read_text(encoding="utf-8")
        self.assertIn('cron: "10 19 * * 1-5"', source)
        self.assertNotIn("\n  workflow_run:", source)
        self.assertIn("github.event_name == 'schedule'", source)
        self.assertIn("github.ref == 'refs/heads/main'", source)
        self.assertIn("github.repository == 'jimmyj92096908-debug/tw-stock-ai'", source)
        self.assertIn("cancel-in-progress: false", source)

    def test_all_write_steps_remain_opt_in_and_bounded(self):
        source = IND.read_text(encoding="utf-8")
        self.assertIn("--per-market 20", source)
        self.assertIn("--apply --per-market 20", source)
        self.assertIn('STOCK_INDICATOR_CATCHUP_WRITE_ENABLED: "yes"', source)
        self.assertIn("inputs.apply == true", source)
        self.assertIn("github.event_name == 'workflow_dispatch'", source)
        self.assertIn("--output indicator-before.json", source)
        self.assertIn("--output indicator-after.json", source)
        self.assertIn("always()", source)
        self.assertIn("indicator-bounded-catchup-evidence", source)
        self.assertNotIn("linewebhook", source.lower())

    def test_score_rebuild_runs_after_successful_scheduled_indicator_only(self):
        source = SCORE.read_text(encoding="utf-8")
        self.assertIn('Verified History Indicator Catch-Up', source)
        self.assertIn("github.event.workflow_run.event == 'schedule'", source)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", source)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", source)
        self.assertIn("github.event.workflow_run.repository.full_name == github.repository", source)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.apply == true", source)
        self.assertNotIn("github.event.workflow_run.event == 'workflow_dispatch'", source)


if __name__ == "__main__":
    unittest.main()
