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
        self.assertIn("github.event.workflow_run.conclusion == 'success'", workflow)
        self.assertIn("python src/stock_db_audit.py --json", workflow)
        self.assertIn("covered/universe < 0.95", workflow)
        self.assertIn("twstock-audit.json", workflow)
        self.assertNotIn("ON CONFLICT", workflow)
        self.assertNotIn("INSERT INTO", workflow)
        self.assertNotIn("LINE_CHANNEL_ACCESS_TOKEN", workflow)


if __name__ == "__main__":
    unittest.main()
