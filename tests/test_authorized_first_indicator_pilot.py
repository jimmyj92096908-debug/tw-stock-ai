"""One-time owner-authorized Neon batch activation safety contracts.

No production operations are performed when these tests run.
"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/authorized-first-indicator-pilot-20261120.yml"
NIGHTLY = ROOT / ".github/workflows/daily-indicator-catchup.yml"
MARKER = "ACTIVATE-ONE-TIME-20261120-STOCK-PILOT"


class AuthorizedFirstIndicatorPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.nightly = NIGHTLY.read_text(encoding="utf-8")

    def test_explicit_one_time_guard_only_main_push_and_first_attempt(self):
        source = self.workflow
        self.assertIn("  push:\n    branches: [\"main\"]", source)
        self.assertIn('github.repository == \'jimmyj92096908-debug/tw-stock-ai\'', source)
        self.assertIn("github.ref == 'refs/heads/main'", source)
        self.assertIn("github.event_name == 'push'", source)
        self.assertIn("github.run_attempt == 1", source)
        self.assertIn(MARKER, source)
        self.assertNotIn("\n  workflow_dispatch:", source)
        self.assertNotIn("\n  schedule:", source)

    def test_pilot_is_strictly_smaller_than_approved_full_batch(self):
        self.assertIn("python src/batch_indicator_catchup.py --per-market 2", self.workflow)
        self.assertIn("python src/batch_indicator_catchup.py --apply --per-market 2", self.workflow)
        self.assertIn("python src/batch_indicator_catchup.py --apply --per-market 20", self.nightly)
        self.assertIn('STOCK_INDICATOR_CATCHUP_WRITE_ENABLED: "yes"', self.workflow)

    def test_one_shot_and_recurring_indicator_job_share_write_lock(self):
        guard = "group: twstock-indicator-catchup"
        self.assertIn(guard, self.workflow)
        self.assertIn(guard, self.nightly)
        self.assertIn("cancel-in-progress: false", self.workflow)

    def test_real_completion_requires_readonly_before_after_and_proof(self):
        required = [
            "indicator_schedule_probe.py --output indicator-before.json",
            "indicator_schedule_probe.py --output indicator-after.json",
            "indicator_batch_reconcile.py",
            "indicator-progress-proof.json",
            "if: success()",
            "if: always()",
            "actions/upload-artifact@v4",
            "tests.test_indicator_batch_reconcile",
        ]
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.workflow)

    def test_scope_excludes_line_and_other_mutations(self):
        self.assertNotIn("linewebhook", self.workflow.lower())
        self.assertNotIn("LINE_CHANNEL_ACCESS_TOKEN", self.workflow)
        self.assertNotIn("LINE_CHANNEL_SECRET", self.workflow)
        self.assertNotIn("trade_order", self.workflow.lower())
        self.assertNotIn("checkout -b", self.workflow.lower())
        self.assertIn("secrets.DATABASE_URL", self.workflow)
        self.assertIn("permissions:\n  contents: read", self.workflow)


if __name__ == "__main__":
    unittest.main()
