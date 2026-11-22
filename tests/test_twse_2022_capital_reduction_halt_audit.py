"""Fail-closed synthetic tests: real 2022 issuer halts are never fake-filled."""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch
import sys
import unittest

from scripts.twse_2022_capital_reduction_halt_audit import (
    APPROVED_SOURCES, DATE_END, DATE_START, EXPECTED_MARKET_SESSIONS,
    FROZEN_STOCKS, HALTS, SQL_SESSIONS, SQL_STOCK_DAYS,
    TWSE_PRIMARY, TWSE_SECONDARY, _halt_trade_dates, _read_neon, assess,
)


def source_market_dates():
    # The two documented exchange holidays during Sep-Dec 2022 are not halts.
    official_holidays = {date(2022, 9, 9), date(2022, 10, 10)}
    d = DATE_START
    days = []
    while d <= DATE_END:
        if d.weekday() < 5 and d not in official_holidays:
            days.append(d)
        d += timedelta(days=1)
    assert len(days) == EXPECTED_MARKET_SESSIONS
    return days


def sample_panel(days):
    market = set(days)
    halts = _halt_trade_dates() & {
        (sid, d) for sid in HALTS for d in market
    }
    rows = []
    for sid in FROZEN_STOCKS:
        for day in days:
            if (sid, day) in halts:
                continue
            source = (TWSE_SECONDARY if sid in ("2330", "2327", "2603")
                      else TWSE_PRIMARY)
            rows.append((sid, day, source))
    return rows


class CapitalReductionHaltTests(unittest.TestCase):
    def setUp(self):
        self.days = source_market_dates()
        self.rows = sample_panel(self.days)

    def test_two_documented_2022_halts_are_not_missing_trade_prices(self):
        result = assess(self.days, self.rows)
        self.assertEqual(result["observed_official_market_sessions"], 84)
        self.assertEqual(result["expected_stock_market_day_pairs"], 1680)
        self.assertEqual(result["observed_distinct_stock_market_day_pairs"], 1666)
        self.assertEqual(result["documented_cash_reduction_halt_stock_days"], 14)
        self.assertEqual(result["unexplained_missing_stock_days"], 0)
        self.assertEqual(result["stocks_with_all_84_market_days"], 18)
        self.assertEqual(len(result["documented_halts"]), 2)
        self.assertEqual(result["neon_writes"], 0)
        self.assertEqual(result["suspended_sessions_imputed_or_persisted"], 0)
        self.assertFalse(result["corporate_action_cash_reduction_adjusted_total_returns_verified"])
        self.assertFalse(result["actual_original_pit_publication_timestamps_verified"])
        self.assertEqual(result["live_model_release_decision"], "BLOCKED")

    def test_exchange_holiday_in_september_does_not_count_as_halt(self):
        result = assess(self.days, self.rows)
        by_stock = {x["stock_id"]: x for x in result["documented_halts"]}
        self.assertEqual(by_stock["2603"]["confirmed_official_market_nontrading_days"], 7)
        self.assertEqual(by_stock["2327"]["confirmed_official_market_nontrading_days"], 7)
        self.assertNotIn(date(2022, 9, 9), self.days)

    def test_unexpected_missing_genuine_stock_date_fails_closed(self):
        rows = [x for x in self.rows if not (
            x[0] == "2330" and x[1] == date(2022, 10, 19))]
        with self.assertRaisesRegex(ValueError, "Unexplained"):
            assess(self.days, rows)

    def test_a_real_price_inside_announced_halt_fails_closed(self):
        rows = self.rows + [("2603", date(2022, 9, 7), TWSE_PRIMARY)]
        with self.assertRaisesRegex(ValueError, "non-trading suspension"):
            assess(self.days, rows)

    def test_duplicate_exact_source_stock_day_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "Duplicate identical"):
            assess(self.days, self.rows + [self.rows[0]])

    def test_two_official_sources_same_stock_day_do_not_double_count(self):
        row = ("2330", date(2022, 12, 30), TWSE_PRIMARY)
        result = assess(self.days, self.rows + [row])
        self.assertEqual(result["observed_distinct_stock_market_day_pairs"], 1666)
        self.assertEqual(sum(result["stock_source_rows_by_official_provenance"].values()), 1667)

    def test_unrecognized_stock_and_unapproved_source_refused(self):
        with self.assertRaisesRegex(ValueError, "Unrequested"):
            assess(self.days, self.rows + [("1589", self.days[0], TWSE_PRIMARY)])
        with self.assertRaisesRegex(ValueError, "Unrequested"):
            assess(self.days, self.rows + [("2330", self.days[0], "FAKE_SOURCE")])
        self.assertEqual(APPROVED_SOURCES,
                         frozenset((TWSE_PRIMARY, TWSE_SECONDARY)))

    def test_mismatched_primary_calendar_is_not_silently_accepted(self):
        with self.assertRaisesRegex(ValueError, "exactly 84"):
            assess(self.days[:-1], self.rows[:-20])
        with self.assertRaisesRegex(ValueError, "exactly 84"):
            assess(self.days[:-1] + [self.days[0]], self.rows)
        with self.assertRaisesRegex(ValueError, "Unrequested"):
            assess(self.days, self.rows + [("2330", date(2022, 9, 9), TWSE_PRIMARY)])

    def test_provenance_notice_precedes_corporate_action(self):
        for spec in HALTS.values():
            self.assertLess(spec["notice_date"], spec["first"])
            self.assertLess(spec["last"], spec["new_share_trading"])
            self.assertTrue(spec["notice"].startswith("https://"))
        self.assertEqual(set(HALTS), {"2327", "2603"})

    def test_neon_pooled_conn_has_no_startup_options_and_readonly_sql(self):
        statements, calls = [], []
        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def execute(self, sql, params=None):
                statements.append((sql.strip(), params))
            def fetchall(self): return []
        class Connection:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def cursor(self): return Cursor()
            def rollback(self): statements.append(("ROLLBACK", None))
        def connect(*args, **kwargs):
            calls.append((args, kwargs))
            return Connection()
        with patch.dict(sys.modules, {"psycopg": SimpleNamespace(connect=connect)}):
            with patch.dict("os.environ", {"DATABASE_URL": "postgresql://fake"}, clear=False):
                self.assertEqual(_read_neon(), ([], []))
        self.assertEqual(calls[0][1], {"connect_timeout": 15})
        self.assertEqual([x[0] for x in statements],
                         ["SET TRANSACTION READ ONLY",
                          "SET LOCAL statement_timeout = '90s'",
                          SQL_SESSIONS.strip(),
                          SQL_STOCK_DAYS.strip(),
                          "ROLLBACK"])
        self.assertEqual(statements[3][1], (list(FROZEN_STOCKS),))
        for query in (SQL_SESSIONS, SQL_STOCK_DAYS):
            self.assertTrue(query.strip().startswith("SELECT"))
            self.assertNotIn("DELETE ", query.upper())
            self.assertNotIn("INSERT ", query.upper())
            self.assertNotIn("UPDATE ", query.upper())


if __name__ == "__main__":
    unittest.main()
