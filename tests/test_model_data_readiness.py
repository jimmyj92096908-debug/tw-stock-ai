"""Unit tests for the non-trading, fail-closed readiness audit."""
import sys
from datetime import date
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from model_data_readiness import build_report, historical_cutoff, release_reasons


class ReadinessAuditTests(unittest.TestCase):
    def test_historical_cutoff_leap_day(self):
        self.assertEqual(historical_cutoff(date(2024, 2, 29)), date(2019, 2, 28))

    def test_failed_saved_holdout_cannot_approve(self):
        evidence = {
            "model_version": "test",
            "holdout_research_gate_passed": False,
            "holdout_is_pristine_independent_validation": False,
            "requires_new_unseen_future_holdout": True,
            "holdout": {"model_mean_net_excess": -0.021},
        }
        report = build_report(evidence, date(2026, 11, 22))
        self.assertEqual(report["model_gate"], "BLOCKED")
        self.assertFalse(report["live_trading_approved"])
        self.assertFalse(report["line_signal_delivery_approved"])
        self.assertFalse(report["database_writes"])
        self.assertIsNone(report["coverage"])
        self.assertEqual(len(report["blocking_reasons"]), 4)

    def test_positive_not_independent_still_blocked(self):
        evidence = {
            "holdout_research_gate_passed": True,
            "holdout_is_pristine_independent_validation": False,
            "requires_new_unseen_future_holdout": False,
            "holdout": {"model_mean_net_excess": 0.01},
        }
        self.assertIn("holdout_not_independent", release_reasons(evidence))

    def test_clean_values_only_require_review(self):
        evidence = {
            "holdout_research_gate_passed": True,
            "holdout_is_pristine_independent_validation": True,
            "requires_new_unseen_future_holdout": False,
            "holdout": {"model_mean_net_excess": 0.01},
        }
        self.assertEqual(build_report(evidence, date(2026, 11, 22))["model_gate"],
                         "REQUIRES_INDEPENDENT_REVIEW")


if __name__ == "__main__":
    unittest.main()
