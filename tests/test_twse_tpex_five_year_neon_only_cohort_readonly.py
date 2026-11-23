"""Neon-only five-year stock maturity / official current-listing audit tests."""
from __future__ import annotations

from datetime import date
from unittest import TestCase
from unittest.mock import Mock, patch

from scripts import twse_tpex_five_year_neon_only_cohort_readonly as audit


START = date(2021, 11, 23)
END = date(2026, 11, 23)


def stock(market, n=900, mature=50):
    return {
        "market": market, "active_current_listed": n,
        "stock_days0": 1,
        "stock_days1_59": 2,
        "stock_days60_239": 5,
        "stock_days240_479": 100,
        "stock_days480_999": n - 108 - mature,
        "stock_days1000_plus": mature,
        "min_stock_valid_days": 0,
        "max_stock_valid_days": 1100,
    }


def years():
    return [
        {
            "market": market,
            "year": y,
            "neon_observed_stock_price_dates": days,
            "dates_with_500_current_stock_bars": max(0, days - 2),
            "stored_valid_current_stock_bars": days * 700,
        }
        for market in audit.MARKETS for y, days in ((2022, 240), (2024, 245))
    ]


def report():
    return audit.evaluate([stock("twse"), stock("tpex", n=850)],
                          years(), {"bytes":650_000_000},
                          start=START, end=END)


class FiveYearNeonOnlyReadOnlyTests(TestCase):
    def test_six_year_segments_and_no_fake_absent_days(self):
        result = report()
        self.assertEqual(result["scope"], audit.SCOPE)
        self.assertEqual(result["model_release"], "BLOCKED")
        self.assertEqual(result["production_neon_writes"], 0)
        self.assertEqual(result["line_messages_sent"], 0)
        self.assertTrue(result["excludes_owner_private_aes_and_non_neon_source_history"])
        self.assertTrue(result["current_listed_issuers_only_not_historical_pit_membership"])
        self.assertFalse(result["five_year_history_completed"])
        self.assertFalse(result["historical_dividends_splits_total_return_verified"])
        self.assertFalse(result["walkforward_future_holdout_validated"])
        for market, n in (("twse", 900), ("tpex", 850)):
            x = result["market"][market]
            self.assertEqual(x["official_current_listed_stocks_excluding_1589"], n)
            self.assertEqual(x["with_at_least_1000_valid_stored_days"], 50)
            self.assertEqual(x["with_at_least_240_valid_stored_days"], n - 8)
            self.assertEqual(len(x["yearly_neon_source_observations"]), 6)
            by = {e["year"]: e for e in x["yearly_neon_source_observations"]}
            self.assertEqual(by[2021]["days_with_any_neon_eligible_source_bars"], 0)
            self.assertEqual(by[2022]["days_with_any_neon_eligible_source_bars"], 240)
            self.assertEqual(by[2023]["days_with_any_neon_eligible_source_bars"], 0)
            self.assertEqual(by[2026]["neon_stored_valid_source_stock_bars"], 0)
        self.assertEqual(result["database_bytes"], 650_000_000)
        self.assertFalse(result["internal_stop_threshold_reached"])

    def test_storage_warning_never_unlocks_paid_writes(self):
        x = audit.evaluate([stock("twse"), stock("tpex",n=850)],
                           years(), {"bytes":810_000_000},start=START,end=END)
        self.assertTrue(x["internal_stop_threshold_reached"])
        self.assertFalse(x["paid_upgrade_requested"])
        self.assertFalse(x["five_year_history_completed"])

    def test_bad_issuer_counts_and_incoherent_distribution_refused(self):
        for records in (
            [stock("twse")],
            [stock("twse"), stock("twse")],
            [stock("twse"), stock("tpex",n=600)],
            [stock("twse"), dict(stock("tpex",n=850), stock_days0=3)],
            [stock("twse"), dict(stock("tpex",n=850), stock_days1000_plus=-1)],
        ):
            with self.assertRaises(ValueError):
                audit.evaluate(records, years(), {"bytes":600_000_000},
                               start=START, end=END)

    def test_too_many_days_future_and_duplicate_market_years_refused(self):
        bad = [dict(years()[0], neon_observed_stock_price_dates=370)]
        with self.assertRaises(ValueError):
            audit.evaluate([stock("twse"),stock("tpex",n=850)],bad,
                           {"bytes":10},start=START,end=END)
        duplicate = years() + [years()[0]]
        with self.assertRaises(ValueError):
            audit.evaluate([stock("twse"),stock("tpex",n=850)],duplicate,
                           {"bytes":10},start=START,end=END)
        future = [dict(years()[0], year=2027)]
        with self.assertRaises(ValueError):
            audit.evaluate([stock("twse"),stock("tpex",n=850)],future,
                           {"bytes":10},start=START,end=END)

    def test_overcount_issuer_stock_bars_rejected(self):
        over = [dict(years()[0],stored_valid_current_stock_bars=999_999)]
        with self.assertRaises(ValueError):
            audit.evaluate([stock("twse"),stock("tpex",n=850)],over,
                           {"bytes":10},start=START,end=END)

    def test_rolling_calendar_fixed_window_and_invalid_dates(self):
        self.assertEqual(audit.five_year_window(END),(START,END))
        self.assertEqual(audit.five_year_window(date(2028,2,29)),
                         (date(2023,2,28),date(2028,2,29)))
        with self.assertRaises(ValueError):
            audit.five_year_window("2026-11-23")
        with self.assertRaises(ValueError):
            audit.five_year_window(date(2022,1,1))

    def test_sql_excludes_1589_delisted_and_unknown_sources(self):
        for sql in (audit.STOCK_SQL, audit.YEAR_SQL):
            self.assertIn("official_current_listed",sql)
            self.assertIn("o.stock_id <> '1589'",sql)
            self.assertIn("model_stock_exclusions",sql)
            self.assertNotIn("UPDATE public",sql.upper())
            self.assertNotIn("DELETE FROM",sql.upper())
            for source in ("TWSE_MI_INDEX_ALLBUT0999","TWSE_STOCK_DAY",
                           "TPEX_DATED_OTC_EW","TPEX_DAILY_CLOSE_OPENAPI"):
                self.assertIn(source,sql)
        self.assertIn("READ ONLY",audit.capture.__code__.co_consts)

    def test_live_connector_uses_one_repeatable_read_only_transaction(self):
        conn=Mock()
        conn.__enter__=Mock(return_value=conn)
        conn.__exit__=Mock(return_value=False)
        stockcur=Mock();stockcur.fetchall.return_value=[stock("twse"),stock("tpex",n=850)]
        yearcur=Mock();yearcur.fetchall.return_value=years()
        meta=Mock();meta.fetchone.return_value={"bytes":650_000_000}
        cmd=Mock();cmd.fetchall.return_value=[]
        def execute(sql, *args):
            if sql==audit.STOCK_SQL: return stockcur
            if sql==audit.YEAR_SQL: return yearcur
            if sql==audit.META_SQL: return meta
            return cmd
        conn.execute.side_effect=execute
        with patch("psycopg.connect",return_value=conn) as connector:
            stocks, annual, size=audit.capture(
                "postgresql://private.invalid/mydb",start=START,end=END)
        self.assertEqual(len(stocks),2)
        self.assertEqual(len(annual),4)
        self.assertEqual(size["bytes"],650_000_000)
        connector.assert_called_once()
        statements=[call.args[0] for call in conn.execute.call_args_list]
        self.assertTrue(any("REPEATABLE READ, READ ONLY" in stmt
                            for stmt in statements))
        self.assertTrue(any("statement_timeout" in stmt for stmt in statements))
        conn.rollback.assert_called_once()

    def test_no_database_url_rejected(self):
        with self.assertRaises(ValueError):
            audit.capture("",start=START,end=END)


if __name__=="__main__":
    import unittest
    unittest.main()
