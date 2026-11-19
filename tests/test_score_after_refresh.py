"""Offline checks for the opt-in composite-score workflow runner."""
import io
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import score_after_refresh


class ScoreAfterRefreshTests(unittest.TestCase):
    def test_runner_normalizes_db_url_and_calls_score_builder_once(self):
        with (
            patch.object(score_after_refresh, "normalize_database_url",
                         return_value="postgresql://reader@example.invalid/twstock") as norm,
            patch.object(score_after_refresh, "calculate_all",
                         return_value=27) as builder,
        ):
            count = score_after_refresh.rebuild_scores(
                "postgresql://placeholder.invalid/unused"
            )
        self.assertEqual(count, 27)
        norm.assert_called_once_with("postgresql://placeholder.invalid/unused")
        builder.assert_called_once_with("postgresql://reader@example.invalid/twstock")

    def test_refuses_missing_db_credential(self):
        with self.assertRaisesRegex(ValueError, "DATABASE_URL"):
            score_after_refresh.rebuild_scores("")
        with patch.dict(os.environ, {"DATABASE_URL": ""}):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL"):
                score_after_refresh.main()

    def test_workflow_cannot_auto_write_without_explicit_opt_in(self):
        path = Path(__file__).resolve().parents[1] / ".github/workflows/composite-after-market-refresh.yml"
        workflow = path.read_text(encoding="utf-8")
        self.assertIn("vars.ENABLE_AUTOMATIC_COMPOSITE_SCORES == 'true'", workflow)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", workflow)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.apply == true", workflow)
        self.assertIn("default: false", workflow)
        self.assertNotIn("schedule:", workflow)

    def test_logs_only_processed_count_not_db_credentials(self):
        buf = io.StringIO()
        with (
            patch.dict(os.environ, {"DATABASE_URL": "postgresql://secret-in-test.invalid/db"}),
            patch.object(score_after_refresh, "rebuild_scores", return_value=5),
            redirect_stdout(buf),
        ):
            score_after_refresh.main()
        output = buf.getvalue()
        self.assertIn("處理 5 檔", output)
        self.assertNotIn("secret-in-test", output)
        self.assertNotIn("postgresql://", output)


if __name__ == "__main__":
    unittest.main()
