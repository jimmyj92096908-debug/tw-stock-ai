import unittest
from datetime import date

from src.ohlc_quality_report import build_report


class TestOHLCQualityReport(unittest.TestCase):
    def test_report_classifies_missing_ohlc_without_inventing_no_trade(self):
        rows = [
            {"market": "tpex", "stock_id": "1259", "stock_name": "安心",
             "trade_date": date(2026, 10, 5), "open": None, "high": None,
             "low": None, "close": None, "volume": 1, "source": "official"},
            {"market": "tpex", "stock_id": "1259", "stock_name": "安心",
             "trade_date": date(2026, 10, 6), "open": None, "high": None,
             "low": None, "close": None, "volume": 0, "source": "official"},
        ]
        report = build_report(rows)
        self.assertTrue(report["read_only"])
        self.assertFalse(report["database_modified"])
        self.assertEqual(report["totals"]["positive_volume_no_ohlc"], 1)
        self.assertEqual(report["totals"]["zero_volume_no_ohlc_unconfirmed"], 1)
        self.assertEqual(report["by_stock"][0]["stock_name"], "安心")

    def test_source_conflicts_are_not_claimed_from_single_normalized_source(self):
        report = build_report([
            {"market": "twse", "stock_id": "2330", "stock_name": "台積電",
             "trade_date": date(2026, 11, 18), "open": 100, "high": 102,
             "low": 99, "close": 101, "volume": 1000, "source": "twse"}
        ])
        self.assertEqual(
            report["source_conflicts"]["status"],
            "not_determinable_from_daily_prices",
        )


if __name__ == "__main__":
    unittest.main()
