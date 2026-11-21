"""Five-year TPEx per-year source dates vs per-stock history: no false claims."""
from datetime import date
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock,patch
from scripts import tpex_five_year_stock_maturity_audit as m

ROOT=Path(__file__).resolve().parents[1]

def stocks():
    return {"current_master":898,"days0":0,"days1_59":11,
        "days60_119":5,"days120_239":32,"days240_479":833,
        "days480_719":1,"days720_999":0,"days1000_plus":16}

def years():
    return [
        {"year":2021,"anchored_sessions":29,"official_full_market_sessions":0},
        {"year":2022,"anchored_sessions":246,"official_full_market_sessions":0},
        {"year":2023,"anchored_sessions":239,"official_full_market_sessions":0},
        {"year":2024,"anchored_sessions":242,"official_full_market_sessions":0},
        {"year":2025,"anchored_sessions":243,"official_full_market_sessions":233},
        {"year":2026,"anchored_sessions":213,"official_full_market_sessions":213},
    ]

def meta():
    return {"latest_session":date(2026,11,20),"bytes":378_000_000}

class FiveYearPerStockMaturityTests(TestCase):
    def test_actual_annual_and_current_stock_master_are_separately_reconciled(self):
        result=m.assess(stocks(),years(),meta())
        self.assertEqual(result["five_year_stock_master_today"],898)
        self.assertEqual(result["total_independently_anchored_market_sessions"],1212)
        self.assertEqual(result["source_proven_full_market_sessions"],446)
        self.assertEqual(result["still_unfilled_anchored_market_sessions"],766)
        self.assertEqual(result["current_stock_master_with_at_least_240_valid_days"],850)
        self.assertEqual(result["current_stock_master_with_at_least_480_valid_days"],17)
        self.assertEqual(result["current_stock_master_with_at_least_1000_valid_days"],16)
        self.assertEqual(result["market_years"][0]["official_market_coverage_percent"],0)
        self.assertEqual(result["market_years"][-1]["official_market_coverage_percent"],100)
        self.assertTrue(result["raw_source_date_count_is_not_per_stock_5y_completeness"])
        self.assertTrue(result["current_stock_master_is_not_historical_listed_universe"])
        self.assertFalse(result["ipo_delisting_and_no_trade_history_independently_audited"])
        self.assertFalse(result["historical_independent_model_holdout_approved"])
        self.assertFalse(result["model_live_trading_approved"])
        self.assertTrue(result["database_read_only"])

    def test_invalid_stock_bucket_or_source_year_count_fails_closed(self):
        for invalid in (
             {**stocks(),"days240_479":832},
             {**stocks(),"days1000_plus":-1},
             {**stocks(),"days0":True},
             {**stocks(),"current_master":0}
        ):
            with self.assertRaises(ValueError):
                m.assess(invalid,years(),meta())
        for invalid in (
            years()[1:],
            years()[:-1]+[years()[-2]],
            years()[:-1]+[{**years()[-1],"anchored_sessions":0}],
            years()[:-1]+[{**years()[-1],"official_full_market_sessions":214}],
            years()[:-1]+[{**years()[-1],"year":2030}],
        ):
            with self.assertRaises((ValueError,RuntimeError)):
                m.assess(stocks(),invalid,meta())
        with self.assertRaises(ValueError):
            m.assess(stocks(),years(),{**meta(),"bytes":True})

    def test_readonly_actual_latest_trade_date_and_source_provenance(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        def query(sql):
            result=MagicMock()
            if sql==m.META_SQL:
                result.fetchone.return_value=meta()
            if sql==m.STOCK_DAYS_SQL:
                result.fetchone.return_value=stocks()
            if sql==m.YEARLY_SQL:
                result.fetchall.return_value=years()
            return result
        conn.execute.side_effect=query
        with patch.object(m.psycopg,"connect",return_value=conn) as connector:
            actual=m.inspect("protected")
        self.assertEqual(actual["scope"],"TPEX_FIVE_YEAR_SOURCE_DEPTH_READ_ONLY_RESEARCH_READINESS")
        self.assertEqual(actual["database_bytes"],378_000_000)
        self.assertIn("default_transaction_read_only=on",connector.call_args.kwargs["options"])
        self.assertIn("REPEATABLE READ READ ONLY",conn.execute.call_args_list[0].args[0])
        self.assertIn("sm.market='tpex'",m.STOCK_DAYS_SQL)
        self.assertIn('EXTRACT(YEAR FROM trade_date)::int AS "year"',m.YEARLY_SQL)
        self.assertIn("dp.source='TPEX_DATED_OTC_EW'",m.YEARLY_SQL)
        self.assertIn("dp.source='TPEX_DAILY_CLOSE_OPENAPI'",m.YEARLY_SQL)
        for sql in (m.STOCK_DAYS_SQL,m.YEARLY_SQL,m.META_SQL):
            self.assertTrue(sql.lstrip().upper().startswith(("WITH","SELECT")))
            self.assertNotIn("INSERT INTO",sql.upper())
            self.assertNotIn("DELETE FROM",sql.upper())
            self.assertNotIn("UPDATE public.",sql.upper())

    def test_workflow_one_time_and_final_postflight_no_prod_write(self):
        wf=(ROOT/".github/workflows/tpex-five-year-stock-maturity.yml").read_text()
        marker=".github/tpex-five-year-stock-maturity-readonly-20261121.txt"
        self.assertIn(marker,wf)
        self.assertIn(".github/tpex-five-year-stock-maturity-sqlfix-20261121.txt",wf)
        self.assertIn("git diff --name-only --diff-filter=A HEAD^ HEAD",wf)
        self.assertIn("  workflow_run:",wf)
        self.assertIn("TPEx Five-Year Dated Market Full Free Campaign",wf)
        self.assertIn("  workflow_dispatch:",wf)
        self.assertNotIn("  schedule:",wf)
        self.assertNotIn("--apply",wf)
        self.assertNotIn("STOCK_TPEX_DATED_HISTORY_WRITE_ENABLED",wf)
        self.assertIn("tpex_five_year_stock_maturity_audit.py",wf)
