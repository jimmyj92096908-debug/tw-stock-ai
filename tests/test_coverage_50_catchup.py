"""Unit-level fail-closed gates for the one-shot research-coverage job."""
import os
import unittest
from unittest.mock import patch
from scripts import coverage_50_catchup as cov


def snapshot(both=82, scores=82, *, universe=200, price_rows=8000, day="2026-11-20"):
    return {
        "universe": universe, "priced": universe,
        "price_rows": price_rows, "latest_price_date": day,
        "technical_current": both, "smc_current": both,
        "both_current": both, "scored_current": scores,
    }


class FiftyPercentCatchUpTests(unittest.TestCase):
    def test_target_uses_all_stock_master_not_priced_or_eligible_only(self):
        self.assertEqual(cov.target_count(1991), 996)
        self.assertEqual(cov.target_count(200), 100)
        with self.assertRaises(ValueError):
            cov.target_count(0)
        self.assertIn("FROM public.stock_master", cov.COVERAGE_SQL)
        self.assertIn("close > 0", cov.COVERAGE_SQL)
        self.assertIn("t.trade_date=p.last_close", cov.COVERAGE_SQL)
        self.assertIn("s.trade_date=p.last_close", cov.COVERAGE_SQL)
        self.assertIn("c.total_score IS NOT NULL", cov.COVERAGE_SQL)

    def test_preview_cannot_write(self):
        with (
            patch.object(cov, "read_snapshot", return_value=snapshot()),
            patch.object(cov, "batch_run", side_effect=AssertionError("write")),
            patch.object(cov, "calculate_all", side_effect=AssertionError("score")),
        ):
            report = cov.run_coverage("fake")
        self.assertFalse(report["indicator_writes_attempted"])
        self.assertFalse(report["score_rebuild_attempted"])

    def test_requires_two_explicit_write_gates(self):
        with patch.dict(os.environ, {"STOCK_50_COVERAGE_WRITE_ENABLED": "",
                                     "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED": "yes"}):
            with self.assertRaisesRegex(ValueError, "write gates"):
                cov.run_coverage("fake", apply=True, max_rounds=2)
        with patch.dict(os.environ, {"STOCK_50_COVERAGE_WRITE_ENABLED": "yes",
                                     "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED": ""}):
            with self.assertRaisesRegex(ValueError, "write gates"):
                cov.run_coverage("fake", apply=True, max_rounds=2)
        with self.assertRaises(ValueError):
            cov.run_coverage("fake", apply=True, max_rounds=56)

    @patch.dict(os.environ, {"STOCK_50_COVERAGE_WRITE_ENABLED": "yes",
                             "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED": "yes"})
    def test_one_bounded_round_then_validated_composite(self):
        with patch.object(cov, "read_snapshot", side_effect=[
            snapshot(), snapshot(102, 82), snapshot(102, 102)
        ]), patch.object(cov, "batch_run", return_value=[
            {"status": "verified"} for _ in range(20)
        ]) as batch, patch.object(cov, "calculate_all", return_value=100) as scores:
            report = cov.run_coverage("fake", apply=True, max_rounds=2)
        self.assertTrue(report["target_verified"])
        self.assertEqual(len(report["batch_rounds"]), 1)
        batch.assert_called_once_with("fake", apply=True, per_market=20)
        scores.assert_called_once_with("fake")

    @patch.dict(os.environ, {"STOCK_50_COVERAGE_WRITE_ENABLED": "yes",
                             "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED": "yes"})
    def test_no_progress_aborts_before_scoring(self):
        with patch.object(cov, "read_snapshot", side_effect=[
            snapshot(), snapshot()
        ]), patch.object(cov, "batch_run", return_value=[
            {"status": "verified"} for _ in range(20)
        ]), patch.object(cov, "calculate_all") as scores:
            with self.assertRaisesRegex(RuntimeError, "coverage gain"):
                cov.run_coverage("fake", apply=True, max_rounds=2)
        scores.assert_not_called()

    def test_changed_market_date_or_price_rows_aborts(self):
        with self.assertRaisesRegex(RuntimeError, "Market source"):
            cov.assert_stable_and_progress(snapshot(), snapshot(102, day="2026-11-21"))
        with self.assertRaisesRegex(RuntimeError, "Market source"):
            cov.assert_stable_and_progress(snapshot(), snapshot(102, price_rows=8001))

    @patch.dict(os.environ, {"STOCK_50_COVERAGE_WRITE_ENABLED": "yes",
                             "STOCK_INDICATOR_CATCHUP_WRITE_ENABLED": "yes"})
    def test_incomplete_final_scores_rejected(self):
        with patch.object(cov, "read_snapshot", side_effect=[
            snapshot(), snapshot(102, 82), snapshot(102, 90)
        ]), patch.object(cov, "batch_run", return_value=[
            {"status": "verified"} for _ in range(20)
        ]), patch.object(cov, "calculate_all", return_value=100):
            with self.assertRaisesRegex(RuntimeError, "below 50%"):
                cov.run_coverage("fake", apply=True, max_rounds=2)


if __name__ == "__main__":
    unittest.main()
