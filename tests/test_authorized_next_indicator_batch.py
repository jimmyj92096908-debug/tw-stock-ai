"""One-shot production 20-stock indicator+score batch guard contracts."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=ROOT/".github/workflows/authorized-20-stock-indicator-score-20261120.yml"
DAILY=ROOT/".github/workflows/daily-indicator-catchup.yml"

class AuthorizedNextIndicatorBatchWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=WORKFLOW.read_text(encoding="utf-8")
        cls.daily=DAILY.read_text(encoding="utf-8")

    def test_only_one_special_main_push_can_enable_writes(self):
        s=self.source
        for token in (
            "github.repository == 'jimmyj92096908-debug/tw-stock-ai'",
            "github.ref == 'refs/heads/main'",
            "github.event_name == 'push'",
            "github.run_attempt == 1",
            "ACTIVATE-ONCE-20261120-NEXT20-INDICATOR",
            "needs: offline-contract",
        ):
            self.assertIn(token,s)
        self.assertNotIn("\n  workflow_dispatch:",s)
        self.assertNotIn("\n  schedule:",s)

    def test_batch_keeps_existing_20_per_market_cap_and_savepoint(self):
        s=self.source
        self.assertIn("python src/batch_indicator_catchup.py --per-market 20",s)
        self.assertIn("python src/batch_indicator_catchup.py --apply --per-market 20",s)
        self.assertIn('STOCK_INDICATOR_CATCHUP_WRITE_ENABLED: "yes"',s)
        self.assertIn("group: twstock-indicator-catchup",s)
        self.assertIn("group: twstock-indicator-catchup",self.daily)
        self.assertIn("cancel-in-progress: false",s)
        self.assertIn("if: success()",s)

    def test_real_indicator_and_score_proof_are_mandatory(self):
        s=self.source
        for text in (
            "indicator-before.json","indicator-after.json",
            "indicator_batch_reconcile.py","indicator-progress-proof.json",
            "score-before.json","score-after.json",
            "indicator_score_followthrough.py","indicator-to-score-proof.json",
            "scripts/score_after_refresh.py","actions/upload-artifact@v4",
            "if: always()",
        ):
            self.assertIn(text,s)

    def test_score_and_indicator_scope_remains_research_only(self):
        s=self.source.lower()
        for string in (
            "line_channel_secret","line_channel_access_token",
            "linewebhook","trading_enabled: true","trade_order",
        ):
            self.assertNotIn(string,s)
        self.assertIn("permissions:\n  contents: read",self.source)

if __name__=="__main__":
    unittest.main()
