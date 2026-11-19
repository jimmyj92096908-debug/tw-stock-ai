"""Offline tests for the read-only stock data coverage audit."""
import unittest
from datetime import date

from src.stock_db_audit import (
    COVERAGE_SQL, GLOBAL_DATES_SQL, SCORE_MATCH_SQL, SAMPLES_SQL,
    REFRESH_STATUS_SQL, collect_audit, format_audit, iso_date,
)


class _Cursor:
    def __init__(self, refresh_exists=True):
        self.refresh_exists = refresh_exists
        self.calls = []
        self.sql = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.sql = sql
        self.calls.append((sql, params))
        # This test intentionally fails on accidental INSERT/UPDATE/DELETE.
        assert sql.lstrip().upper().startswith("SELECT") or (
            sql.lstrip().upper().startswith("WITH")
        )

    def fetchone(self):
        if self.sql == GLOBAL_DATES_SQL:
            return {
                "latest_price_date": date(2026, 11, 19),
                "latest_technical_date": date(2026, 11, 19),
                "latest_smc_date": date(2026, 11, 19),
                "latest_score_date": date(2026, 11, 18),
            }
        if self.sql == SCORE_MATCH_SQL:
            return {
                "score_date": date(2026, 11, 18),
                "scored": 18, "matched_price": 17, "missing_price": 1,
            }
        if "to_regclass" in self.sql:
            return {"name": "market_data_refresh_state" if self.refresh_exists else None}
        raise AssertionError("Unexpected fetchone")

    def fetchall(self):
        if self.sql == COVERAGE_SQL:
            return [
                {"market": "twse", "universe": 1093, "priced": 21,
                 "missing_prices": 1072, "over_7_days_behind_latest": 5},
                {"market": "tpex", "universe": 898, "priced": 19,
                 "missing_prices": 879, "over_7_days_behind_latest": 5},
            ]
        if self.sql == SAMPLES_SQL:
            return [
                {"market": "twse", "stock_id": "2330",
                 "stock_name": "台積電", "last_price": date(2026, 10, 30)},
                {"market": "tpex", "stock_id": "6488",
                 "stock_name": "環球晶", "last_price": None},
            ]
        if self.sql == REFRESH_STATUS_SQL:
            return [
                {"status": "success", "total": 14},
                {"status": "never_attempted", "total": 1977},
            ]
        raise AssertionError("Unexpected fetchall")


class _Connection:
    def __init__(self, refresh_exists=True):
        self.cur = _Cursor(refresh_exists=refresh_exists)

    def cursor(self, **_kwargs):
        return self.cur


class StockAuditTests(unittest.TestCase):
    def test_collect_and_format_readonly_snapshot(self):
        conn = _Connection()
        result = collect_audit(conn)
        self.assertEqual(result["latest"]["latest_price_date"], "2026-11-19")
        self.assertEqual(result["latest"]["latest_score_date"], "2026-11-18")
        self.assertEqual(result["score"]["matched_price"], 17)
        self.assertEqual(result["samples"][0]["last_price"], "2026-10-30")
        self.assertEqual(len(conn.cur.calls), 6)
        self.assertEqual(conn.cur.calls[1][1], (date(2026, 11, 19),))
        self.assertEqual(conn.cur.calls[3][1], (["2330", "6488", "6213"],))

        output = format_audit(result)
        self.assertIn("有行情股票：40/1991", output)
        self.assertIn("評分日 2026-11-18：評分 18；有同日收盤價 17", output)
        self.assertIn("輪替更新 never_attempted：1977", output)
        self.assertIn("不可視為全市場分析", output)

    def test_optional_refresh_table_can_be_absent(self):
        conn = _Connection(refresh_exists=False)
        snapshot = collect_audit(conn)
        self.assertEqual(snapshot["refresh_state"], [])
        self.assertEqual(len(conn.cur.calls), 5)

    def test_null_date_and_empty_composite_count_not_fabricated(self):
        self.assertIsNone(iso_date(None))
        self.assertEqual(iso_date(date(2026, 11, 19)), "2026-11-19")
        self.assertIn("COUNT(c.stock_id)::int AS scored", SCORE_MATCH_SQL)
        self.assertNotIn("COUNT(*)::int AS scored", SCORE_MATCH_SQL)


if __name__ == "__main__":
    unittest.main()
