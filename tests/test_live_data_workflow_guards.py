"""Offline contract tests for owner's authorized, low-volume DB workflows.

No live credentials are accessed by this module.
"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LiveDataWorkflowGuardTests(unittest.TestCase):
    def _read(self, filename):
        return (ROOT / ".github" / "workflows" / filename).read_text(encoding="utf-8")

    def test_history_enrichment_capped_and_manual_preview_default(self):
        workflow = self._read("daily-bounded-history-enrichment.yml")
        self.assertIn("cron: \"15 17 * * 1-5\"", workflow)
        self.assertIn("default: false", workflow)
        self.assertIn("STOCK_ENRICHMENT_WRITE_ENABLED: \"yes\"", workflow)
        self.assertIn("--apply --per-market 2", workflow)
        self.assertIn("tests.test_bounded_history_enrichment", workflow)
        self.assertIn("github.repository == 'jimmyj92096908-debug/tw-stock-ai'", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)

    def test_dated_twse_history_is_limited_and_manual_default_is_dry_run(self):
        workflow=self._read("daily-twse-dated-history.yml")
        self.assertIn('cron: "50 17 * * 1-5"',workflow)
        self.assertIn("default: false",workflow)
        self.assertIn('STOCK_TWSE_HISTORY_WRITE_ENABLED: "yes"',workflow)
        self.assertIn("--apply --batch-days 8 --lookback-days 366",workflow)
        self.assertIn("github.ref == 'refs/heads/main'",workflow)
        self.assertIn("tests.test_twse_dated_history",workflow)

    def test_indicator_proposed_independent_schedule_is_single_bounded_write(self):
        workflow=self._read("daily-indicator-catchup.yml")
        # A second automatic workflow_run source could write twice/day.
        self.assertIn('cron: "10 19 * * 1-5"',workflow)
        self.assertNotIn("\\n  workflow_run:",workflow)
        self.assertIn("github.event_name == 'schedule'",workflow)
        self.assertIn("github.ref == 'refs/heads/main'",workflow)
        self.assertIn("github.repository == 'jimmyj92096908-debug/tw-stock-ai'",workflow)
        self.assertIn("github.event_name == 'workflow_dispatch'",workflow)
        self.assertIn("inputs.apply == true",workflow)
        self.assertIn("--apply --per-market 20",workflow)
        self.assertIn('STOCK_INDICATOR_CATCHUP_WRITE_ENABLED: "yes"',workflow)
        self.assertIn("default: false",workflow)
        self.assertIn("indicator-before.json",workflow)
        self.assertIn("indicator-after.json",workflow)

    def test_score_recompute_requires_successful_official_feed(self):
        workflow = self._read("composite-after-market-refresh.yml")
        self.assertIn('Official Taiwan Market Daily Snapshot (Authorized)', workflow)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", workflow)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", workflow)
        self.assertIn("github.event.workflow_run.repository.full_name == github.repository", workflow)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.apply == true", workflow)
        self.assertIn("default: false", workflow)

    def test_integrity_monitor_never_writes_and_only_uploads_aggregates(self):
        workflow = self._read("twstock-data-quality-monitor.yml")
        self.assertIn("TW Stock Data Quality Monitor (Read-Only)", workflow)
        self.assertIn("Composite Scores After Verified Official Snapshot", workflow)
        # A -> B -> C -> D workflow_run chain exceeds GitHub's supported
        # nesting; keep an independent read-only schedule as a fallback.
        self.assertIn('cron: "0 20 * * 1-5"', workflow)
        self.assertIn("github.event_name == 'schedule'", workflow)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", workflow)
        self.assertIn("python src/stock_db_audit.py --json", workflow)
        self.assertIn("covered/universe < 0.95", workflow)
        self.assertIn("twstock-audit.json", workflow)
        self.assertNotIn("ON CONFLICT", workflow)
        self.assertNotIn("INSERT INTO", workflow)
        self.assertNotIn("LINE_CHANNEL_ACCESS_TOKEN", workflow)


if __name__ == "__main__":
    unittest.main()
