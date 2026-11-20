"""No-network tests for score-date fallback in LINE daily-report SQL."""
import unittest
from datetime import date
from unittest.mock import patch

from src.send_line_report import load_report, format_report


class FakeCursor:
    def __init__(self, latest_score_date):
        self.calls = []
        self.data = [
            {"trade_date": date(2026, 11, 19)},
            [{"market": "twse", "stocks": 1093}, {"market": "tpex", "stocks": 898}],
            [{"market": "twse", "stocks": 14}, {"market": "tpex", "stocks": 11}],
            {"stocks": 1108},  # prior-date close coverage; SELECT only
            {"score_date": latest_score_date},
            {"rows": 18 if latest_score_date else 0,
             "scored": 18 if latest_score_date else 0,
             "chip_integrated": 0, "avg_coverage": 0.7},
            {"latest_date": date(2026, 11, 19), "rows": 2},
            {"latest_date": date(2026, 11, 19), "rows": 2},
            ([{"market": "twse", "stock_id": "6213", "stock_name": "聯茂",
               "close": 438.5, "price_change": -3,
               "total_score": 45.96, "short_term_score": 50,
               "swing_score": 45, "long_term_score": 42}] if latest_score_date else []),
            [{"line_user_id": "U-example-not-real"}],
        ]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return self.data[len(self.calls) - 1]

    def fetchall(self):
        return self.data[len(self.calls) - 1]


class FakeConnection:
    def __init__(self, score_date):
        self.cur = FakeCursor(score_date)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.cur


class ReportQueryTests(unittest.TestCase):
    def test_returns_latest_prior_score_with_matching_historical_price(self):
        fake = FakeConnection(date(2026, 11, 18))
        with patch("src.send_line_report.psycopg.connect", return_value=fake):
            report = load_report("postgresql://placeholder.invalid/test")
        self.assertEqual(report["trade_date"], date(2026, 11, 19))
        self.assertEqual(report["score_date"], date(2026, 11, 18))
        self.assertEqual(report["previous_prices_count"], 1108)
        self.assertEqual(report["scores"]["scored"], 18)
        self.assertEqual(report["top"][0]["stock_id"], "6213")
        self.assertEqual(fake.cur.calls[3][1], (date(2026, 11, 19),))
        self.assertIn("COUNT(DISTINCT (market, stock_id))", fake.cur.calls[3][0])
        self.assertEqual(fake.cur.calls[4][1], (date(2026, 11, 19),))
        self.assertEqual(fake.cur.calls[5][1], (date(2026, 11, 18),))
        self.assertEqual(fake.cur.calls[8][1], (date(2026, 11, 18),))
        self.assertIn("p.trade_date=%s", fake.cur.calls[8][0])
        self.assertIn("c.as_of_date=p.trade_date", fake.cur.calls[8][0])
        self.assertEqual(len(fake.cur.calls), 10)
        self.assertIn("綜合評分資料日：2026-11-18", format_report(report))

    def test_no_score_date_does_not_invent_rankings(self):
        fake = FakeConnection(None)
        with patch("src.send_line_report.psycopg.connect", return_value=fake):
            report = load_report("postgresql://placeholder.invalid/test")
        self.assertIsNone(report["score_date"])
        self.assertEqual(report["top"], [])
        self.assertIsNone(fake.cur.calls[8][1][0])
        self.assertIn("尚無可用評分", format_report(report))


if __name__ == "__main__":
    unittest.main()
