"""Daily LINE pre-cutover monitor is a read-only safety check, not a switch."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=ROOT/".github/workflows/line-cutover-readiness-observe.yml"
SCRIPT=ROOT/"scripts/line_readonly_live_preflight.py"


class LineReadOnlyScheduleContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow=WORKFLOW.read_text(encoding="utf-8")
        cls.code=SCRIPT.read_text(encoding="utf-8")

    def test_daily_taipei_schedule_and_manual_inspection(self):
        source=self.workflow
        self.assertIn('cron: "40 18 * * *"',source)
        self.assertIn("  workflow_dispatch:",source)
        self.assertIn("github.repository == 'jimmyj92096908-debug/tw-stock-ai'",source)
        self.assertIn("github.ref == 'refs/heads/main'",source)
        self.assertIn("github.event_name != 'pull_request'",source)
        self.assertIn("cancel-in-progress: false",source)

    def test_watch_is_readonly_no_line_cutover_or_messages(self):
        source=self.workflow
        self.assertIn("python scripts/line_readonly_live_preflight.py",source)
        self.assertIn("permissions:\n  contents: read",source)
        self.assertIn("LINE_CHANNEL_ACCESS_TOKEN:",source)
        self.assertNotIn("LINE_CHANNEL_SECRET:",source)
        self.assertNotIn("LINE_SINGLE_ACCOUNT_ENABLED: true",source)
        for denied in (
            "LINE_CANARY_TEST_ENABLED",
            "line_gateway_canary.py --apply",
            "line_webhook_control.py --apply",
            "deploy_function", "linewebhook --apply",
            "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED",
            "workflow_dispatch:\n    inputs:\n      apply:",
        ):
            self.assertNotIn(denied,source)
        self.assertIn("GET /health",self.code)
        self.assertIn("ready_for_cutover\": False",self.code)
        self.assertIn("production_webhook_changed\": False",self.code)
        self.assertIn("line_message_sent\": False",self.code)

    def test_daily_monitor_keeps_no_secret_artifacts_and_explicit_gate(self):
        source=self.workflow
        self.assertIn("line-readiness-observe.json",source)
        self.assertIn("official_signed_empty_canary_performed",source)
        self.assertIn("real_line_message_e2e_verified",source)
        self.assertIn("**Cutover ready: FALSE",source)
        self.assertIn("if-no-files-found: ignore",source)
        self.assertIn("retention-days: 14",source)
        self.assertIn("tests.test_line_readonly_schedule",source)
        self.assertEqual(source.count('"tests/test_line_readonly_schedule.py"'),2)


if __name__=="__main__":
    unittest.main()
