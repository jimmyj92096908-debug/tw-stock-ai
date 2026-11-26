"""Synthetic fixed-bin calibration regression tests."""
from datetime import date, timedelta
import unittest

from src.v3_probability_calibration import fixed_bin_calibration


class CalibrationTests(unittest.TestCase):
    def rows(self):
        start = date(2024, 1, 2)
        return [
            dict(market="TWSE", stock_id=str(2000+j), currently_listed=True,
                 signal_date=(start+timedelta(days=i)).isoformat(),
                 exit_date=(start+timedelta(days=i+1)).isoformat(),
                 training_labels_through=(start+timedelta(days=i-1)).isoformat(),
                 probability=0.85, net_return=0.02 if j < 4 else -0.01)
            for i in range(20) for j in range(5)
        ]

    def evaluate(self, rows, p=0.85, cutoff="2024-02-01"):
        return fixed_bin_calibration(rows, decision_date=cutoff, probability=p)

    def test_rate_is_not_sizing_permission(self):
        r = self.evaluate(self.rows())
        self.assertEqual(r["observations"], 100)
        self.assertEqual(r["distinct_signal_dates"], 20)
        self.assertAlmostEqual(r["empirical_net_win_rate"], 0.8)
        self.assertTrue(r["descriptive_rate_available"])
        self.assertAlmostEqual(r["brier_score"], 0.1625)
        self.assertIsNone(r["conservative_probability_for_sizing"])
        self.assertEqual(r["model_release"], "BLOCKED")

    def test_sparse_and_empty_bins(self):
        self.assertFalse(self.evaluate(self.rows()[:99])["descriptive_rate_available"])
        r = self.evaluate(self.rows(), 0.95)
        self.assertEqual(r["observations"], 0)
        self.assertIsNone(r["empirical_net_win_rate"])

    def test_temporal_embargo(self):
        rows = self.rows()
        with self.assertRaises(ValueError):
            self.evaluate(rows, cutoff=rows[-1]["exit_date"])
        rows[0]["training_labels_through"] = rows[0]["signal_date"]
        with self.assertRaises(ValueError):
            self.evaluate(rows)

    def test_duplicates_exclusions_and_invalid_values(self):
        rows = self.rows()
        with self.assertRaises(ValueError):
            self.evaluate(rows + [rows[0]])
        for patch in ({"stock_id": "1589"}, {"currently_listed": False},
                      {"market": "unknown"}, {"probability": float("nan")},
                      {"net_return": True}):
            with self.subTest(patch=patch):
                with self.assertRaises(ValueError):
                    self.evaluate([dict(rows[0], **patch)] + rows[1:])

    def test_bin_boundary_and_flat_trade(self):
        rows = [dict(self.rows()[0], probability=1.0, net_return=0)]
        r = self.evaluate(rows, 1.0)
        self.assertEqual(r["bin_index"], 9)
        self.assertEqual(r["empirical_net_win_rate"], 0)
        self.assertEqual(r["brier_score"], 1)


if __name__ == "__main__":
    unittest.main()
