"""Prevent accidental production corporate-action rebuild on code push."""
from pathlib import Path
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/build-adjusted-prices.yml"


class BuildAdjustedWorkflowGuardTests(unittest.TestCase):
    def test_production_rebuild_requires_manual_opt_in(self):
        src = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", src)
        self.assertIn("default: false", src)
        self.assertIn("inputs.apply == true", src)
        self.assertIn("github.ref == 'refs/heads/main'", src)
        self.assertIn("github.event_name == 'workflow_dispatch'", src)
        self.assertNotIn("  push:", src)
        self.assertNotIn("  schedule:", src)


if __name__ == "__main__":
    unittest.main()
