"""A main-branch-only, source-gated initial factor batch; no extra scheduler."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/".github/workflows/tpex-historical-factor-freshness.yml"


class TPExHistoricalRepairBootstrapTests(unittest.TestCase):
    def test_exact_workflow_only_push_and_existing_schedule(self):
        workflow=PATH.read_text(encoding="utf-8")
        self.assertIn("  push:\n    branches:\n      - main\n",workflow)
        self.assertIn(
            "    paths:\n      - '.github/workflows/tpex-historical-factor-freshness.yml'",
            workflow)
        self.assertIn("- cron: '40 2,14 * * *'",workflow)
        self.assertIn("github.ref == 'refs/heads/main'",workflow)
        self.assertIn("github.event_name == 'push'",workflow)
        self.assertIn("github.event_name == 'schedule'",workflow)
        self.assertIn("inputs.apply == true",workflow)
        self.assertIn("default: false",workflow)
        self.assertNotIn("  workflow_run:",workflow)

    def test_existing_fail_closed_guards_and_budget_are_preserved(self):
        workflow=PATH.read_text(encoding="utf-8")
        self.assertIn("steps.gate.outputs.ready == 'true'",workflow)
        self.assertIn("release_ready(state)",workflow)
        self.assertIn("scripts/tpex_stale_factor_refresh.py --apply --rounds 5",workflow)
        self.assertIn("Rebuild at most 100 stale TPEx stocks",workflow)
        self.assertIn("group: twstock-indicator-catchup",workflow)
        self.assertIn("group: twstock-tpex-dated-official-history",workflow)
        self.assertIn("STOCK_TPEX_STALE_FACTOR_WRITE_ENABLED: 'yes'",workflow)
        self.assertIn("STOCK_TPEX_STALE_SCORE_WRITE_ENABLED: 'yes'",workflow)
        self.assertIn("STOCK_INDICATOR_CATCHUP_WRITE_ENABLED: 'yes'",workflow)
        self.assertNotIn("LINE_CHANNEL",workflow)
        self.assertNotIn("orders",workflow.lower())
        self.assertNotIn("daily_prices UPDATE",workflow)


if __name__=="__main__":
    unittest.main()
