"""Guard the GitHub Actions scheduled research report from release side effects."""
from pathlib import Path
import unittest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/investment-model-readonly-report.yml"


class ScheduledResearchWorkflowTests(unittest.TestCase):
    def test_readonly_model_report_is_regularly_generated_with_fixed_taipei_schedule(self):
        content=WORKFLOW.read_text(encoding="utf-8")
        # 21:30 UTC Mon-Fri = 05:30 Asia/Taipei Tue-Sat, no DST.
        self.assertIn('cron: "30 21 * * 1-5"',content)
        self.assertIn("workflow_dispatch:",content)
        self.assertIn("inputs.market || 'twse'",content)
        self.assertIn("inputs.stock_id || '2330'",content)
        self.assertIn("github.ref == 'refs/heads/main'",content)
        self.assertIn("github.repository == 'jimmyj92096908-debug/tw-stock-ai'",content)
        self.assertIn("cancel-in-progress: false",content)

    def test_scheduled_research_model_cannot_publish_orders_or_send_line(self):
        content=WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("INVESTMENT_MODEL_READONLY:",content)
        self.assertIn("abstain_from_trading",content)
        self.assertIn('d["orders_enabled"] is False',content)
        self.assertIn('d["publish_line_trade_signal"] is False',content)
        self.assertIn("investment_model_pipeline.py --live-readonly",content)
        self.assertIn("upload-artifact@v4",content)
        self.assertIn("retention-days: 14",content)
        for forbidden in (
            "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED",
            "--apply",
            "send_line_report.py",
            "LINE_CHANNEL_ACCESS_TOKEN",
            "GRANT SELECT",
            "deploy_function",
            "orders/place",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden,content)


if __name__ == "__main__":
    unittest.main()
