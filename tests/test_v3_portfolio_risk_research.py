"""Synthetic-only regression checks for aligned covariance and ERC."""
from datetime import date, timedelta
from copy import deepcopy
import unittest

from src.v3_portfolio_risk_research import portfolio_risk_research


class PortfolioRiskTests(unittest.TestCase):
    def histories(self):
        start = date(2024, 1, 1)
        patterns = [[0.01, -0.01, 0.01, -0.01],
                    [0.02, 0.02, -0.02, -0.02],
                    [0.03, -0.03, 0.03, -0.03]]
        return [
            {"market": "TWSE", "stock_id": str(2300+i), "currently_listed": True,
             "returns": [{"date": (start+timedelta(days=j)).isoformat(),
                          "return": p[j%4]} for j in range(64)]}
            for i,p in enumerate(patterns)
        ]

    def evaluate(self, histories, **kwargs):
        args = dict(decision_date="2024-04-01", gross_budget=0.8, cash_budget=0.6)
        args.update(kwargs)
        return portfolio_risk_research(histories, **args)

    def test_equal_risk_and_concentration_warning(self):
        r = self.evaluate(self.histories())
        self.assertEqual(r["observations"], 64)
        self.assertEqual(len(r["high_positive_correlation_pairs"]), 1)
        self.assertAlmostEqual(r["high_positive_correlation_pairs"][0]["correlation"], 1)
        self.assertAlmostEqual(sum(w["relative_risky_weight"] for w in r["weights"]), 1)
        for w in r["weights"]:
            self.assertAlmostEqual(w["relative_variance_contribution"], 1/3, places=6)
            self.assertLessEqual(w["reference_account_weight"], 0.1+1e-12)
        self.assertLessEqual(r["reference_gross_exposure"], 0.3+1e-12)
        self.assertEqual(r["model_release"], "BLOCKED")
        self.assertFalse(r["existing_holdings_integrated"])

    def test_inverse_vol_for_uncorrelated_pair(self):
        r = self.evaluate(self.histories()[:2])
        self.assertAlmostEqual(r["weights"][0]["relative_risky_weight"], 2/3)
        self.assertAlmostEqual(r["weights"][1]["relative_risky_weight"], 1/3)

    def test_cash_and_gross_caps(self):
        for gross, cash in [(0, 1), (1, 0), (0.05, 0.1), (0.1, 0.03)]:
            r = self.evaluate(self.histories(), gross_budget=gross, cash_budget=cash)
            self.assertAlmostEqual(r["reference_gross_exposure"], min(gross,cash))
            self.assertAlmostEqual(sum(w["reference_account_weight"] for w in r["weights"]),
                                   min(gross,cash))

    def test_negative_correlation_and_permutation(self):
        h = self.histories()
        for row in h[2]["returns"]:
            row["return"] *= -1
        r = self.evaluate(h)
        q = self.evaluate(list(reversed(h)))
        a = {w["stock_id"]:w["relative_risky_weight"] for w in r["weights"]}
        b = {w["stock_id"]:w["relative_risky_weight"] for w in q["weights"]}
        for k in a:
            self.assertAlmostEqual(a[k], b[k], places=6)
        for w in r["weights"]:
            self.assertAlmostEqual(w["relative_variance_contribution"], 1/3, places=6)

    def test_invalid_histories(self):
        for change in (
            lambda h: h[0].update(stock_id="1589"),
            lambda h: h[0].update(currently_listed=False),
            lambda h: h[1].update(stock_id=h[0]["stock_id"]),
            lambda h: h[0]["returns"].pop(),
            lambda h: h[0]["returns"][-1].update(date="2024-04-01"),
            lambda h: h[0]["returns"][1].update(date=h[0]["returns"][0]["date"]),
            lambda h: h[0]["returns"][0].update({"return":float("nan")}),
            lambda h: [row.update({"return":0.0}) for row in h[0]["returns"]],
        ):
            h = deepcopy(self.histories())
            change(h)
            with self.assertRaises(ValueError):
                self.evaluate(h)


if __name__ == "__main__":
    unittest.main()
