"""Official first-seen as-of fundamental availability regression suite."""
from __future__ import annotations

from datetime import date,datetime
from pathlib import Path
import os
import unittest
from unittest.mock import MagicMock,patch
from zoneinfo import ZoneInfo

from src.official_fundamental_pit_coverage import (
 FUNDAMENTAL_ASOF_SQL, actual_signal_cutoff, audit_report,
)
from scripts import audit_official_fundamentals_pit as script


def fixture(market,total,known):
    return {
        "market":market, "stock_master":total,
        "observed_income":known,
        "observed_balance":known,
        "observed_revenue":known,
        "quarterly_same_period":known,
        "safe_eps_and_balance":known,
        "debt_to_assets_research_possible":known,
        "current_ratio_research_possible":known,
        "all_three_sources_observed":known,
        "accounting_identity_failures":0,
        "current_ratio_denominator_missing_or_zero":0,
    }


class FundamentalAvailabilityTests(unittest.TestCase):
    def test_real_first_seen_not_fiscal_month_is_only_visible_cutoff(self):
        sql=FUNDAMENTAL_ASOF_SQL
        self.assertEqual(sql.count("first_observed_at<=%s::timestamptz"),3)
        self.assertEqual(sql.count("AND period_end<="),3)
        self.assertEqual(sql.count("DISTINCT ON(market,stock_id)"),3)
        self.assertIn("i.period_end=b.period_end",sql)
        self.assertIn("b.accounting_identity_verified",sql)
        self.assertIn("b.current_liabilities_thousands_ntd>0",sql)
        self.assertIn("public.stock_master sm",sql)
        self.assertIn("all_three_sources_observed",sql)
        self.assertNotIn("DO UPDATE",sql)
        self.assertNotIn("DELETE FROM",sql)
        self.assertNotIn("publi",sql.replace("public.",""))

    def test_valid_trading_day_cutoff_timezone_and_no_future(self):
        now=datetime(2026,11,21,14,55,tzinfo=ZoneInfo("Asia/Taipei"))
        self.assertEqual(
            actual_signal_cutoff("2026-11-20",server_now=now).isoformat(),
            "2026-11-20T13:30:00+08:00")
        with self.assertRaises(ValueError):
            actual_signal_cutoff("2026-11-23",server_now=now)
        with self.assertRaises(ValueError):
            actual_signal_cutoff("2026-11-21",server_now="2026-11-21")
        with self.assertRaises(ValueError):
            actual_signal_cutoff(datetime.now(),server_now=now)

    def test_different_asof_versions_from_input_never_gain_earlier_coverage(self):
        cutoff=actual_signal_cutoff("2026-11-20",server_now=datetime(
            2026,11,21,15,tzinfo=ZoneInfo("Asia/Taipei")))
        past=audit_report([fixture("twse",1100,0),fixture("tpex",891,0)],
                          cutoff=cutoff)
        self.assertEqual(past["totals"]["all_three_sources_observed"],0)
        self.assertEqual(past["all_master_source_joint_coverage_pct"],0)
        future=audit_report([fixture("twse",1100,1053),fixture("tpex",891,891)],
                            cutoff=cutoff)
        self.assertEqual(future["totals"]["all_three_sources_observed"],1944)
        self.assertEqual(future["all_master_source_joint_coverage_pct"],97.64)
        self.assertFalse(future["cashflow_source_verified"])
        self.assertFalse(future["roe_verified"])
        self.assertFalse(future["live_trading_approved"])
        self.assertFalse(future["database_writes"])

    def test_bad_denominators_and_impossible_coverage_fail(self):
        c=actual_signal_cutoff("2026-11-20",server_now=datetime(
            2026,11,21,15,tzinfo=ZoneInfo("Asia/Taipei")))
        for bad in (
            [fixture("twse",1100,0)],
            [fixture("twse",1100,0),fixture("twse",1100,0)],
            [fixture("twse",1100,0),{**fixture("tpex",891,0),"stock_master":0}],
            [fixture("twse",1100,0),{**fixture("tpex",891,0),"observed_balance":-1}],
            [fixture("twse",1100,0),{**fixture("tpex",891,0),"observed_income":892}],
            [fixture("twse",1100,0),{**fixture("tpex",891,0),"quarterly_same_period":1}],
            [fixture("twse",1100,0),{**fixture("tpex",891,0),"safe_eps_and_balance":1}],
            [fixture("twse",1100,0),{**fixture("tpex",891,0),"observed_revenue":True}],
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    audit_report(bad,cutoff=c)

    def test_script_uses_ro_connection_real_db_time_session_and_no_line(self):
        content=(Path(__file__).resolve().parents[1]/
                 "scripts/audit_official_fundamentals_pit.py").read_text()
        self.assertIn("default_transaction_read_only=on",content)
        self.assertIn("REPEATABLE READ READ ONLY",content)
        self.assertIn("SELECT clock_timestamp()",content)
        self.assertIn("VALID_MARKET_SESSION_SQL",content)
        self.assertIn("statement_timeout='25000ms'",content)
        self.assertNotIn("LINE_CHANNEL",content)
        with self.assertRaises(ValueError):
            script.run("")


if __name__=="__main__":
    unittest.main()
