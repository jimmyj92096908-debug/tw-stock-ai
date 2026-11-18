import unittest
from datetime import date

from src.send_line_report import format_report


class LineReportTests(unittest.TestCase):
    def test_formats_data_coverage_and_ranked_watchlist(self):
        data = {
            "trade_date": date(2026, 11, 18),
            "universe": {"twse": 1093, "tpex": 898},
            "prices": {"twse": 16, "tpex": 14},
            "scores": {"scored": 30, "avg_coverage": 0.8},
            "institutional": {"latest_date": date(2026, 11, 18), "rows": 1864},
            "margin": {"latest_date": date(2026, 11, 18), "rows": 1870},
            "top": [{
                "market": "twse", "stock_id": "2330", "stock_name": "台積電",
                "close": 1400, "price_change": 10, "total_score": 88.5,
                "short_term_score": 80, "swing_score": 85, "long_term_score": 90,
                "coverage_weight": 0.8, "component_status": {},
            }],
            "recipients": ["U-test"],
        }
        message = format_report(data)
        self.assertIn("2026-11-18", message)
        self.assertIn("30/1,991", message)
        self.assertIn("2330 台積電", message)
        self.assertIn("非買賣指令", message)

    def test_handles_empty_watchlist_and_stays_within_line_limit(self):
        data = {
            "trade_date": date(2026, 11, 18),
            "universe": {"twse": 1000, "tpex": 900},
            "prices": {"twse": 0, "tpex": 0},
            "scores": {"scored": 0, "avg_coverage": None},
            "institutional": {"latest_date": None, "rows": 0},
            "margin": {"latest_date": None, "rows": 0},
            "top": [], "recipients": [],
        }
        message = format_report(data)
        self.assertIn("目前沒有符合條件", message)
        self.assertLessEqual(len(message), 4900)


if __name__ == "__main__":
    unittest.main()
