"""Manual rollback workflow must never unexpectedly change the LINE endpoint."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LineWebhookWorkflowTests(unittest.TestCase):
    def test_registered_webhook_control_is_manual_and_default_read_only(self):
        p=ROOT / ".github" / "workflows" / "line-webhook-inspect-restore.yml"
        source=p.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:",source)
        self.assertNotIn("schedule:",source)
        self.assertNotIn("  push:",source)
        self.assertIn("default: inspect",source)
        self.assertIn("default: false",source)
        self.assertIn('LINE_WEBHOOK_RESTORE_ENABLED:',source)
        self.assertIn("inputs.action == 'restore' && inputs.apply",source)
        self.assertIn('if [ "$APPLY" != "true" ]',source)
        self.assertIn("github.ref == 'refs/heads/main'",source)
        self.assertNotIn("https://api.line.me/v2/bot/channel/webhook/endpoint",source)
        # All API endpoints are pinned inside the separately tested Python module.


if __name__ == "__main__":
    unittest.main()
