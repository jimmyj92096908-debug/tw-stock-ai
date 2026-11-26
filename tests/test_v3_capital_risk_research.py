"""Synthetic regression tests only: no market performance claims."""
import math
import unittest

from src.v3_capital_risk_research import research_weight, outcome_diagnostics


class CapitalResearchTests(unittest.TestCase):
    def weight(self, **overrides):
        args = dict(conservative_probability=0.8, net_payoff_ratio=2,
                    stop_loss_fraction=0.05, market_exposure_remaining=0.8,
                    sector_exposure_remaining=0.2, cash_available=0.5,
                    portfolio_risk_remaining=0.02, drawdown=0)
        args.update(overrides)
        return research_weight(**args)

    def test_caps_and_abstention(self):
        self.assertAlmostEqual(self.weight(), 0.1)
        self.assertAlmostEqual(self.weight(stop_loss_fraction=0.1), 0.05)
        self.assertAlmostEqual(self.weight(portfolio_risk_remaining=0.001), 0.02)
        self.assertAlmostEqual(self.weight(cash_available=0.03), 0.03)
        self.assertAlmostEqual(self.weight(sector_exposure_remaining=0.02), 0.02)
        self.assertAlmostEqual(self.weight(market_exposure_remaining=0.01), 0.01)
        self.assertEqual(self.weight(conservative_probability=0.7999), 0)
        self.assertEqual(self.weight(net_payoff_ratio=0.1), 0)
        self.assertEqual(self.weight(drawdown=0.1), 0)
        self.assertAlmostEqual(self.weight(drawdown=0.05), 0.05)

    def test_generated_budget_invariants(self):
        for p in (0, 0.79, 0.8, 0.9, 1):
            for stop in (0.001, 0.01, 0.05, 0.25):
                for cash in (0, 0.005, 0.1, 1):
                    w = self.weight(conservative_probability=p,
                                    stop_loss_fraction=stop, cash_available=cash)
                    self.assertGreaterEqual(w, 0)
                    self.assertLessEqual(w, min(0.1, cash) + 1e-12)
                    self.assertLessEqual(w * stop, 0.005 + 1e-12)

    def test_bad_input_fails_closed(self):
        for x in (True, math.nan, math.inf, -1, 1.1, "0.8"):
            with self.assertRaises(ValueError):
                self.weight(conservative_probability=x)
        for x in (0, -1, math.nan):
            with self.assertRaises(ValueError):
                self.weight(stop_loss_fraction=x)
        for x in ([], [True], [math.nan], [-1.1]):
            with self.assertRaises(ValueError):
                outcome_diagnostics(x)

    def test_high_win_rate_can_lose_money(self):
        r = outcome_diagnostics([0.02] * 400 + [-0.10] * 100)
        self.assertEqual(r["net_win_rate"], 0.8)
        self.assertLess(r["mean_net_return"], 0)
        self.assertFalse(r["point_targets_met"])

    def test_targets_never_approve_trading(self):
        r = outcome_diagnostics([0.06] * 400 + [-0.03] * 100)
        self.assertTrue(r["point_targets_met"])
        self.assertAlmostEqual(r["profit_factor"], 8)
        self.assertEqual(r["model_release"], "BLOCKED")
        self.assertFalse(r["trading_approved"])
        self.assertFalse(r["independence_verified"])
        self.assertFalse(r["portfolio_drawdown_verified"])
        self.assertFalse(outcome_diagnostics([0.06] * 4 + [-0.03])["point_targets_met"])

    def test_flat_and_no_losses(self):
        r = outcome_diagnostics([0.01, 0, -0.01])
        self.assertEqual(r["flat"], 1)
        self.assertAlmostEqual(r["net_win_rate"], 1/3)
        self.assertIsNone(outcome_diagnostics([0.01] * 500)["profit_factor"])
        self.assertFalse(outcome_diagnostics([0.01] * 500)["point_targets_met"])


if __name__ == "__main__":
    unittest.main()
