"""A research report must only follow a successful automatic score refresh.

Static workflow contract test: never requests real database credentials or
triggers any write. PR CI can validate the trigger before merge.
"""
from pathlib import Path
import unittest

BASE=Path(__file__).resolve().parents[1] / ".github" / "workflows"

class ResearchReportScoreTriggerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report=(BASE/"first-stage-report.yml").read_text(encoding="utf-8")
        cls.score=(BASE/"composite-after-market-refresh.yml").read_text(encoding="utf-8")
        cls.indicator=(BASE/"daily-indicator-catchup.yml").read_text(encoding="utf-8")

    def test_report_only_listens_to_the_approved_score_workflow(self):
        source=self.report
        self.assertIn('name: First-Stage Research Report (Read-Only)',source)
        self.assertIn('\n  workflow_run:\n    workflows:\n      - "Composite Scores After Verified Official Snapshot"\n    types: [completed]',source)
        self.assertIn("github.event.workflow_run.conclusion == 'success'",source)
        self.assertIn("github.event.workflow_run.head_branch == 'main'",source)
        self.assertIn("github.event.workflow_run.repository.full_name == github.repository",source)
        self.assertIn("github.event.workflow_run.event == 'workflow_run'",source)
        self.assertIn("github.ref == 'refs/heads/main'",source)
        self.assertIn("github.repository == 'jimmyj92096908-debug/tw-stock-ai'",source)

    def test_report_still_has_independent_nightly_fallback(self):
        source=self.report
        self.assertIn('cron: "45 20 * * 1-5"',source)
        self.assertIn('github.event_name == \x27schedule\x27',source)
        self.assertIn('github.event_name == \x27workflow_dispatch\x27',source)
        self.assertIn('github.event_name == \x27push\x27',source)
        self.assertIn("cancel-in-progress: false",source)

    def test_first_stage_readme_entry_change_refreshes_readonly_report(self):
        source=self.report
        # Both pull request tests and main-branch user-entry updates must
        # trigger the report workflow, never a production writer.
        self.assertEqual(source.count('      - "README.md"'),2)
        self.assertIn('twstock-first-stage-research-report',source)

    def test_score_trigger_is_downstream_of_successful_scheduled_indicator(self):
        self.assertIn('Verified History Indicator Catch-Up',self.score)
        self.assertIn("github.event.workflow_run.event == 'schedule'",self.score)
        self.assertIn("github.event.workflow_run.conclusion == 'success'",self.score)
        self.assertIn('cron: "10 19 * * 1-5"',self.indicator)
        self.assertIn('indicator_batch_reconcile.py',self.indicator)

    def test_report_has_no_writers_or_live_trade_signals(self):
        source=self.report
        self.assertIn("python src/stock_db_audit.py --json",source)
        self.assertIn("python scripts/trained_factor_pipeline.py rank",source)
        self.assertIn("twstock-first-stage-research-report",source)
        self.assertIn("permissions:\n  contents: read",source)
        for bad in (
            "--apply --per-market","STOCK_INDICATOR_CATCHUP_WRITE_ENABLED",
            "linewebhook","LINE_CHANNEL_ACCESS_TOKEN","place_order",
            "python scripts/score_after_refresh.py",
        ):
            self.assertNotIn(bad,source)
        self.assertNotIn('\n      - name: Recompute',source)

if __name__=="__main__":
    unittest.main()
