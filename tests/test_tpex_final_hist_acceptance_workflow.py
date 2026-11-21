"""A free one-time follow-on must not confuse job success with 100% research."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=ROOT/".github/workflows/tpex-final-historical-factors.yml"


class TPExFinalHistoricalFactorsWorkflowTests(unittest.TestCase):
    def test_one_exact_file_on_main_and_default_manual_preview(self):
        data=WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("  push:\n    branches:\n      - main\n",data)
        self.assertIn("'.github/workflows/tpex-final-historical-factors.yml'",data)
        self.assertNotIn("  schedule:",data)
        self.assertNotIn("  workflow_run:",data)
        self.assertIn("github.ref == 'refs/heads/main'",data)
        self.assertIn("github.event_name == 'push'",data)
        self.assertIn("github.event_name == 'workflow_dispatch'",data)
        self.assertIn("inputs.apply == true",data)
        self.assertIn("default: false",data)

    def test_writer_serialization_free_plan_and_cap(self):
        data=WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("group: twstock-indicator-catchup",data)
        self.assertIn("group: twstock-tpex-dated-official-history",data)
        self.assertIn("cancel-in-progress: false",data)
        self.assertIn("scripts/tpex_factor_bounded_campaign.py --apply --max-batches 3",data)
        self.assertIn("source-verified historical batches",data)
        self.assertIn("STOCK_TPEX_FACTOR_CAMPAIGN_ENABLED: 'yes'",data)
        self.assertIn("STOCK_TPEX_STALE_FACTOR_WRITE_ENABLED: 'yes'",data)
        self.assertIn("STOCK_TPEX_STALE_SCORE_WRITE_ENABLED: 'yes'",data)
        self.assertIn("STOCK_INDICATOR_CATCHUP_WRITE_ENABLED: 'yes'",data)
        self.assertIn("800_000_000",data)
        self.assertNotIn("LINE_CHANNEL",data)
        self.assertNotIn("UPDATE public.daily_prices",data)
        self.assertNotIn("orders.submit",data)

    def test_full_acceptance_required_or_job_explicit_failure(self):
        text=WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("tpex_historical_factors_current']==state['tpex_eligible'",text)
        self.assertIn("tpex_matched']==state['tpex_eligible'",text)
        self.assertIn("state['bad_legacy_volume']==0",text)
        self.assertIn("state['bad_legacy_turnover']==0",text)
        self.assertIn("full_100_percent_historical_acceptance",text)
        self.assertIn("raise SystemExit('FAIL CLOSED",text)
        self.assertIn("tpex-final-acceptance.json",text)


if __name__=="__main__":
    unittest.main()
