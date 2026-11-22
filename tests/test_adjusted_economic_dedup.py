"""Unittest-discoverable regression guard for duplicate official economic events.

Production Neon has repeated 4919/6213 source event IDs with equal economics.
This suite needs no database credentials, LINE access, or paid services.
"""
from decimal import Decimal
import unittest

from adjusted_prices import adjust_bars


class EconomicEventDedupTests(unittest.TestCase):
    def setUp(self):
        self.bars = [
            {"trade_date": "2026-07-01", "open": 100, "high": 100,
             "low": 100, "close": 100, "volume": 1000},
            {"trade_date": "2026-07-02", "open": 100, "high": 100,
             "low": 100, "close": 100, "volume": 1000},
        ]

    def test_equivalent_official_rows_with_different_ids_and_numeric_formats(self):
        first = {"ex_date": "2026-07-02", "action_type": "CASH_DIVIDEND",
                 "price_factor": Decimal("0.991666666667"),
                 "share_factor": Decimal("1.000000000000"),
                 "cash_amount": None, "stock_amount": None,
                 "source_event_id": "source-v1"}
        second = {"ex_date": "2026-07-02", "action_type": "CASH_DIVIDEND",
                  "price_factor": "0.9916666666670", "share_factor": 1,
                  "source_event_id": "source-v2"}
        output = adjust_bars(self.bars, [first, second])
        self.assertAlmostEqual(output[0]["price_adjustment_factor"],
                               0.991666666667, places=12)
        self.assertAlmostEqual(output[0]["close"], 99.1666666667, places=8)
        self.assertEqual(output[1]["price_adjustment_factor"], 1)
        self.assertEqual(output[0]["volume"], 1000)

    def test_distinct_same_date_economic_actions_still_compound(self):
        first = {"ex_date": "2026-07-02", "action_type": "CASH_DIVIDEND",
                 "price_factor": "0.98", "share_factor": "1"}
        second = {"ex_date": "2026-07-02", "action_type": "STOCK_DIVIDEND",
                  "price_factor": "0.95", "share_factor": "1.05"}
        output = adjust_bars(self.bars, [first, second])
        self.assertAlmostEqual(output[0]["close"], 100 * .98 * .95)
        self.assertAlmostEqual(output[0]["volume"], 1000 * 1.05)

    def test_missing_optional_amount_is_not_explicit_zero(self):
        base = {"ex_date": "2026-07-02", "action_type": "OTHER",
                "price_factor": "0.9", "share_factor": "1"}
        output = adjust_bars(self.bars, [base, {**base, "cash_amount": 0}])
        self.assertAlmostEqual(output[0]["price_adjustment_factor"], .81)

    def test_nonfinite_and_nonpositive_factors_fail_closed(self):
        base = {"ex_date": "2026-07-02", "action_type": "CASH_DIVIDEND",
                "share_factor": 1}
        for bad in ("NaN", "Infinity", "-1", "0", None, ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                adjust_bars(self.bars, [{**base, "price_factor": bad}])

    def test_invalid_economic_cash_amount_fails_closed(self):
        with self.assertRaises(ValueError):
            adjust_bars(self.bars, [
                {"ex_date": "2026-07-02", "action_type": "CASH_DIVIDEND",
                 "price_factor": "0.98", "share_factor": "1",
                 "cash_amount": "NaN"}
            ])


if __name__ == "__main__":
    unittest.main()
