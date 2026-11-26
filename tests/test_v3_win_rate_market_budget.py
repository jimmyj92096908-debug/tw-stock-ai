"""Synthetic regression tests for block bootstrap and incremental exposure."""
from datetime import date, timedelta
import unittest

from src.v3_win_rate_market_budget import block_win_rate_research, incremental_market_budget


class WinRateMarketTests(unittest.TestCase):
    def rows(self, clustered=False):
        start = date(2024, 1, 2)
        return [
            dict(market="TWSE", stock_id=str(2300+j), currently_listed=True,
                 signal_date=(start+timedelta(days=i)).isoformat(),
                 exit_date=(start+timedelta(days=i+1)).isoformat(),
                 training_labels_through=(start+timedelta(days=i-1)).isoformat(),
                 net_return=0.02 if (i<80 if clustered else j<4) else -0.01)
            for i in range(100) for j in range(5)
        ]

    def evaluate(self, rows, cutoff="2024-05-01"):
        return block_win_rate_research(rows, decision_date=cutoff)

    def test_stable_cohorts_do_not_approve_trades(self):
        r = self.evaluate(self.rows())
        self.assertEqual(r["point_win_rate"], 0.8)
        self.assertEqual(r["sensitivity_lower_estimate"], 0.8)
        self.assertTrue(r["research_80pct_screen"])
        self.assertFalse(r["verified_confidence_bound"])
        self.assertIsNone(r["conservative_probability_for_sizing"])
        self.assertEqual(r["model_release"], "BLOCKED")

    def test_clustered_losses_weaken_lower_estimate(self):
        rows = self.rows(clustered=True)
        r = self.evaluate(rows)
        self.assertEqual(r["point_win_rate"], 0.8)
        self.assertLess(r["sensitivity_lower_estimate"], 0.8)
        self.assertFalse(r["research_80pct_screen"])
        self.assertEqual(r, self.evaluate(list(reversed(rows))))

    def test_sparse_and_invalid_outcomes(self):
        rows = self.rows()
        self.assertIsNone(self.evaluate(rows[:-1])["sensitivity_lower_estimate"])
        with self.assertRaises(ValueError):
            self.evaluate(rows, cutoff=rows[-1]["exit_date"])
        with self.assertRaises(ValueError):
            self.evaluate(rows + [rows[0]])
        for patch in ({"stock_id": "1589"}, {"currently_listed": False},
                      {"training_labels_through": rows[0]["signal_date"]},
                      {"net_return": float("nan")}):
            with self.assertRaises(ValueError):
                self.evaluate([dict(rows[0], **patch)] + rows[1:])

    def budget(self, **overrides):
        args = dict(regime="UPTREND", volatile_heuristic=False,
                    existing_gross_exposure=0.2, cash_available=0.6, drawdown=0)
        args.update(overrides)
        return incremental_market_budget(**args)

    def test_market_and_drawdown_caps(self):
        for regime, expected in (("UPTREND",0.6), ("RANGE_OR_TRANSITION",0.2),
                                 ("DOWNTREND",0), ("UNKNOWN_HISTORY",0),
                                 ("EXTREME_RISK",0)):
            self.assertAlmostEqual(self.budget(regime=regime)["incremental_exposure_budget"], expected)
        self.assertAlmostEqual(self.budget(volatile_heuristic=True)["incremental_exposure_budget"], 0.2)
        self.assertAlmostEqual(self.budget(drawdown=0.05)["incremental_exposure_budget"], 0.2)
        self.assertEqual(self.budget(drawdown=0.10)["incremental_exposure_budget"], 0)
        self.assertAlmostEqual(self.budget(cash_available=0.03)["incremental_exposure_budget"], 0.03)

    def test_existing_positions_and_invalid_inputs(self):
        r = self.budget(regime="DOWNTREND", existing_gross_exposure=0.5, cash_available=0.5)
        self.assertTrue(r["existing_exposure_above_ceiling"])
        self.assertFalse(r["forced_sale"])
        self.assertFalse(r["trading_approved"])
        for patch in ({"regime":"invalid"}, {"volatile_heuristic":1},
                      {"existing_gross_exposure":0.8}, {"drawdown":float("inf")}):
            with self.assertRaises(ValueError):
                self.budget(**patch)


if __name__ == "__main__":
    unittest.main()
