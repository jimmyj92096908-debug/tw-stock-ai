"""Strict 5-year TPEx official market-price import safety and free-tier tests."""
from datetime import date
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock,patch

from scripts import tpex_five_year_market_backfill as m

ROOT=Path(__file__).resolve().parents[1]

class FiveYearTPExBackfillTests(TestCase):
    def test_five_year_trading_day_anchor_not_fabricated(self):
        self.assertEqual(m.floor_five_years(date(2026,11,20)),date(2021,11,20))
        self.assertEqual(m.floor_five_years(date(2028,2,29)),date(2023,2,28))
        with self.assertRaises(ValueError):
            m.floor_five_years(None)
        self.assertEqual(m.MAX_DATES,1250)
        self.assertEqual(m.MIN_ANCHORS,10)
        self.assertLess(m.MAX_FAILURES,10)
        self.assertEqual(m.MAX_DB_BYTES,800_000_000)
        self.assertEqual(m.SAFE_DAY_BYTES,5_000_000)

    def test_selected_source_dates_have_existing_independent_anchor(self):
        conn=MagicMock()
        cur=conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value=[
            (date(2026,6,30),18,0),
            (date(2022,12,30),16,0),
        ]
        values=m.select_sparse_days(conn,last_day=date(2026,11,20),
                                    allowed_count=900,max_days=5)
        self.assertEqual(len(values),2)
        self.assertEqual(values[1]["saved_closes"],16)
        sql,args=cur.execute.call_args.args
        self.assertIn("valid_count>=10",sql)
        self.assertIn("official_dated<",sql)
        self.assertEqual(args,(date(2021,11,20),date(2026,11,20),720,500,5))
        cur.fetchall.return_value=[(date(2022,12,30),9,0)]
        with self.assertRaises(RuntimeError):
            m.select_sparse_days(conn,last_day=date(2026,11,20),
                                 allowed_count=900,max_days=5)
        for limit in (0,1251,True):
            with self.assertRaises(ValueError):
                m.select_sparse_days(conn,last_day=date(2026,11,20),
                                     allowed_count=900,max_days=limit)

    def test_nonexistent_official_data_and_mixed_source_fail_closed(self):
        conn=MagicMock()
        day=date(2025,12,31)
        allowed={("tpex",str(1000+n)) for n in range(900)}
        with patch.object(m,"select_candidates",return_value=[
            {"market":"tpex","stock_id":"1234","trade_date":day}]),\
             patch.object(m,"verify_source_date",return_value={
                 "compared":10,"matched":9,"mismatched":1}):
            with self.assertRaisesRegex(ValueError,"Insufficient old-date"):
                m.verified_source_bars(conn,day,allowed,
                    fetcher=lambda d:{"bars":[{"market":"tpex"}]})
        with self.assertRaisesRegex(ValueError,"missing actual bars"):
            m.verified_source_bars(conn,day,allowed,fetcher=lambda d:{})

    def test_preview_is_sql_only_zero_http_and_zero_writes(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        allowed={("tpex",str(1000+x)) for x in range(900)}
        with patch.object(m.psycopg,"connect",return_value=conn),\
             patch.object(m,"ensure_size",return_value=310000000),\
             patch.object(m,"load_allowed",return_value=allowed),\
             patch.object(m,"get_latest_day",return_value=date(2026,11,20)),\
             patch.object(m,"select_sparse_days",return_value=[
                 {"trade_date":date(2025,12,31),"saved_closes":18,"previous_official":0}]),\
             patch.object(m,"verified_source_bars") as source,\
             patch.object(m,"write_missing") as insert:
            result=m.run("protected",apply=False)
        self.assertFalse(result["apply"])
        self.assertEqual(result["candidate_dates_in_this_batch"],1)
        self.assertEqual(result["source_requests"],0)
        self.assertEqual(result["new_price_rows"],0)
        self.assertFalse(result["full_five_year_official_history_verified"])
        self.assertFalse(result["all_historical_derived_factors_recalculated"])
        source.assert_not_called()
        insert.assert_not_called()

    def test_apply_requires_two_separate_approved_gates_and_finite_budget(self):
        with patch.dict(os.environ,{},clear=True),\
             patch.object(m.psycopg,"connect") as connect:
            with self.assertRaises(PermissionError):
                m.run("protected",apply=True)
            connect.assert_not_called()
        with patch.dict(os.environ,{"STOCK_TPEX_FIVE_YEAR_SOURCE_WRITE_ENABLED":"yes"},clear=True):
            with self.assertRaises(PermissionError):
                m.run("protected",apply=True)
        for bad in (0,1251,True):
            with self.assertRaises(ValueError):
                m.run("protected",max_days=bad)
        for pause in (0,11):
            with self.assertRaises(ValueError):
                m.run("protected",pause_seconds=pause)

    def test_actual_verified_day_is_exact_only_insert_and_counted(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        allowed={("tpex",str(1000+x)) for x in range(900)}
        day=date(2025,12,31)
        stocks=[{"market":"tpex","stock_id":"1000","trade_date":day}]
        first=[{"trade_date":day,"saved_closes":18,"previous_official":0}]
        flags={"STOCK_TPEX_FIVE_YEAR_SOURCE_WRITE_ENABLED":"yes",
               "STOCK_TPEX_DATED_HISTORY_WRITE_ENABLED":"yes"}
        with patch.dict(os.environ,flags),\
             patch.object(m.psycopg,"connect",return_value=conn) as connect,\
             patch.object(m,"ensure_size",return_value=311000000),\
             patch.object(m,"load_allowed",return_value=allowed),\
             patch.object(m,"get_latest_day",return_value=date(2026,11,20)),\
             patch.object(m,"select_sparse_days",side_effect=[first,[]]),\
             patch.object(m,"verified_source_bars",return_value=(stocks,{
                 "compared":18,"matched":18,"mismatched":0})) as proof,\
             patch.object(m,"write_missing",return_value=850) as insert,\
             patch.object(m.time,"sleep") as pause:
            result=m.run("protected",apply=True,max_days=1,pause_seconds=1)
        self.assertEqual(result["source_requests"],1)
        self.assertEqual(result["verified_days"],1)
        self.assertEqual(result["new_price_rows"],850)
        self.assertEqual(result["unprocessed_dates"],0)
        self.assertTrue(result["complete_source_date_coverage"])
        self.assertFalse(result["full_five_year_official_history_verified"])
        self.assertFalse(result["raw_existing_price_keys_overwritten"])
        self.assertFalse(result["LINE_messages_sent"])
        self.assertFalse(result["paid_plan_requested"])
        self.assertTrue(connect.call_args.kwargs["autocommit"])
        insert.assert_called_once_with(conn,"tpex",day,stocks)
        proof.assert_called_once()
        pause.assert_called_once_with(1)

    def test_source_failure_is_audit_and_no_raw_insert(self):
        conn=MagicMock()
        conn.__enter__.return_value=conn
        allowed={("tpex",str(1000+x)) for x in range(900)}
        day=date(2022,12,30)
        first=[{"trade_date":day,"saved_closes":16,"previous_official":0}]
        flags={"STOCK_TPEX_FIVE_YEAR_SOURCE_WRITE_ENABLED":"yes",
               "STOCK_TPEX_DATED_HISTORY_WRITE_ENABLED":"yes"}
        with patch.dict(os.environ,flags),\
             patch.object(m.psycopg,"connect",return_value=conn),\
             patch.object(m,"ensure_size",return_value=311000000),\
             patch.object(m,"load_allowed",return_value=allowed),\
             patch.object(m,"get_latest_day",return_value=date(2026,11,20)),\
             patch.object(m,"select_sparse_days",side_effect=[first,first]),\
             patch.object(m,"verified_source_bars",side_effect=ValueError("No matching old quotes")),\
             patch.object(m,"write_missing") as insert,\
             patch.object(m.time,"sleep"):
            result=m.run("protected",apply=True,max_days=1,pause_seconds=1)
        self.assertEqual(result["failures"][0]["date"],day.isoformat())
        self.assertEqual(result["source_requests"],1)
        self.assertEqual(result["verified_days"],0)
        self.assertEqual(result["new_price_rows"],0)
        self.assertFalse(result["complete_source_date_coverage"])
        insert.assert_not_called()

    def test_one_shot_job_and_automatic_full_handoff_not_cron(self):
        w=(ROOT/".github/workflows/tpex-five-year-market-canary.yml").read_text()
        big=(ROOT/".github/workflows/tpex-five-year-market-full.yml").read_text()
        self.assertIn("tpex-five-year-market-20261121",w)
        self.assertIn("git diff --name-only --diff-filter=A HEAD^ HEAD",w)
        self.assertNotIn("  schedule:",w)
        self.assertIn("--apply --max-days 10",w)
        self.assertIn("twstock-tpex-dated-official-history",w)
        self.assertIn("workflow_run:",big)
        self.assertIn("conclusion == 'success'",big)
        self.assertIn("head_branch == 'main'",big)
        self.assertIn("event == 'push'",big)
        self.assertIn("--apply --max-days 1250",big)
        self.assertNotIn("  schedule:",big)
        self.assertIn("twstock-tpex-dated-official-history",big)
        for f in ("STOCK_TPEX_FIVE_YEAR_SOURCE_WRITE_ENABLED",
                  "STOCK_TPEX_DATED_HISTORY_WRITE_ENABLED"):
            self.assertIn(f,w)
            self.assertIn(f,big)
