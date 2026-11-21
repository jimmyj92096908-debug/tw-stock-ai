"""Offline safety tests for gradual 60+ session indicator enrichment."""
import os
from contextlib import contextmanager
import unittest
from datetime import date
from unittest.mock import patch

from src import batch_indicator_catchup as ind


class Cursor:
    def __init__(self):
        self.calls=[]
        self.params=None
        self.sql=None
    def __enter__(self):return self
    def __exit__(self,*_):return False
    def execute(self,sql,params=None):
        self.calls.append((sql,params))
        self.sql=sql
        self.params=params
    def fetchall(self):
        market=self.params[0]
        return [{
            "market":market,
            "stock_id":"2330" if market=="twse" else "6488",
            "close_days":74,
            "latest_close":date(2026,11,19),
            "technical_rows":0,
            "smc_rows":0,
            "has_latest_technical":False,
            "has_latest_smc":False,
        }]
    def fetchone(self):
        return {"adjusted_rows":74,"technical_rows":74,"smc_rows":74,
                "adjusted_has_latest":True,
                "technical_has_latest":True,
                "smc_has_latest":True}


class Connection:
    def __init__(self):
        self.cur=Cursor()
        self.tx_committed=0
        self.tx_rolled_back=0
        self.records=[]
    def __enter__(self):return self
    def __exit__(self,*_):return False
    def cursor(self):return self.cur
    @contextmanager
    def transaction(self):
        # Models a PostgreSQL savepoint with independent rollback per stock.
        original=list(self.records)
        try:
            yield
        except Exception:
            self.records[:]=original
            self.tx_rolled_back+=1
            raise
        else:
            self.tx_committed+=1


class IndicatorCatchupTests(unittest.TestCase):
    def test_requires_database_and_explicit_apply_opt_in(self):
        with self.assertRaisesRegex(ValueError,"DATABASE_URL"):
            ind.run("")
        for n in (0,-1,21,100):
            with self.assertRaisesRegex(ValueError,"per_market"):
                ind.run("fake",per_market=n)
        with patch.dict(os.environ,{"STOCK_INDICATOR_CATCHUP_WRITE_ENABLED":""}):
            with self.assertRaisesRegex(ValueError,"opt-in"):
                ind.run("fake",apply=True)
        with self.assertRaisesRegex(ValueError,"Unsafe market"):
            ind.select_candidates(Connection(),"not-listed",2)
        self.assertIn("MIN_VERIFIED_PRICE_DAYS",dir(ind))

    def test_opt_in_240_session_history_gate_keeps_normal_default(self):
        conn=Connection()
        with patch.object(ind.psycopg,"connect",return_value=conn):
            result=ind.run("fake",per_market=2,markets=("twse",),
                           min_verified_price_days=240)
        self.assertEqual(len(result),1)
        self.assertEqual(conn.cur.calls[0][1],("twse",240,2))
        for value in (59,241,0,True):
            with self.assertRaisesRegex(ValueError,"verified history"):
                ind.run("fake",min_verified_price_days=value)
        self.assertEqual(ind.MIN_VERIFIED_PRICE_DAYS,60)

    def test_market_subset_avoids_unrequested_twse_calculations(self):
        conn=Connection()
        with patch.object(ind.psycopg,"connect",return_value=conn):
            rows=ind.run("fake",per_market=1,markets=("tpex",))
        self.assertEqual([x["market"] for x in rows],["tpex"])
        self.assertEqual(len(conn.cur.calls),1)
        self.assertEqual(conn.cur.calls[0][1],("tpex",60,1))
        for markets in ((),("tpex","tpex"),("unknown",),("twse","tpex","extra")):
            with self.assertRaisesRegex(ValueError,"markets"):
                ind.run("fake",markets=markets)

    def test_dry_run_does_not_recalculate_or_write(self):
        conn=Connection()
        with (
            patch.object(ind.psycopg,"connect",return_value=conn),
            patch.object(ind,"build_adjusted_stock",side_effect=AssertionError("unexpected write")),
        ):
            result=ind.run("fake",per_market=2)
        self.assertEqual([r["status"] for r in result],["dry-run","dry-run"])
        self.assertEqual(len(conn.cur.calls),2)
        self.assertEqual(conn.cur.calls[0][1],("twse",60,2))
        self.assertEqual(conn.cur.calls[1][1],("tpex",60,2))
        self.assertIn("p.stock_id<>'1808'",ind.CANDIDATES_SQL)

    def test_successful_apply_recomputes_all_factors_and_verifies_rows(self):
        conn=Connection()
        with (
            patch.dict(os.environ,{"STOCK_INDICATOR_CATCHUP_WRITE_ENABLED":"yes"}),
            patch.object(ind.psycopg,"connect",return_value=conn),
            patch.object(ind,"build_adjusted_stock",return_value=74) as adjusted,
            patch.object(ind,"calculate_technical_stock",return_value=74) as tech,
            patch.object(ind,"calculate_smc_stock",return_value=74) as smc,
        ):
            result=ind.run("fake",apply=True,per_market=1)
        self.assertEqual([x["status"] for x in result],["verified","verified"])
        self.assertEqual(adjusted.call_count,2)
        self.assertEqual(tech.call_count,2)
        self.assertEqual(smc.call_count,2)
        self.assertEqual(conn.cur.calls[1][1],("twse","2330",date(2026,11,19)))

    def test_candidate_sql_recovers_stale_dates_even_when_old_row_count_is_high(self):
        sql=ind.CANDIDATES_SQL
        self.assertIn("NOT has_latest_technical",sql)
        self.assertIn("NOT has_latest_smc",sql)
        self.assertIn("'8937'",sql)
        self.assertIn("'2330'",sql)
        self.assertIn("technical_rows < close_days",sql)
        self.assertIn("smc_rows < close_days",sql)
        # Never admit incorrect latest dates just because counts are higher.
        self.assertIn("technical_has_latest",ind.VERIFY_SQL)
        self.assertIn("smc_has_latest",ind.VERIFY_SQL)
        self.assertIn("adjusted_has_latest",ind.VERIFY_SQL)

    def test_stale_latest_technical_date_rolls_back_even_if_counts_are_full(self):
        conn=Connection()
        base=conn.cur.fetchone
        def stale_date():
            result=base()
            return {**result,"technical_has_latest":False}
        conn.cur.fetchone=stale_date
        with (
            patch.dict(os.environ,{"STOCK_INDICATOR_CATCHUP_WRITE_ENABLED":"yes"}),
            patch.object(ind.psycopg,"connect",return_value=conn),
            patch.object(ind,"build_adjusted_stock",return_value=74),
            patch.object(ind,"calculate_technical_stock",return_value=74),
            patch.object(ind,"calculate_smc_stock",return_value=74)
        ):
            report=ind.run("fake",apply=True,per_market=1)
        self.assertEqual([x["status"] for x in report],["failed","failed"])
        self.assertEqual(conn.tx_rolled_back,2)
        self.assertEqual(conn.tx_committed,0)

    def test_max_indicator_date_after_last_actual_close_is_not_automatically_bad(self):
        # Real tpex/2235: Nov 20 has a NULL closing price. Valid last
        # close is Nov 19, while technicals happen to contain a Nov 20 row.
        sql=ind.CANDIDATES_SQL
        self.assertIn("t.trade_date=p.latest_close",sql)
        self.assertIn("s.trade_date=p.latest_close",sql)
        self.assertIn("latest_valid_close_date",ind.VERIFY_SQL)
        self.assertNotIn("technical_last",ind.VERIFY_SQL)
        self.assertNotIn("smc_last",ind.VERIFY_SQL)

    def test_partial_stock_failure_is_rolled_back_and_next_stock_succeeds(self):
        conn=Connection()
        def adjust(_conn,market,stock):
            conn.records.append((market,stock,"adjusted"))
            return 74
        def technical(_conn,market,stock):
            conn.records.append((market,stock,"technical"))
            if market=="twse":
                raise RuntimeError("PRIVATE-FAILED-DATABASE-OPERATION")
            return 74
        def smc(_conn,market,stock):
            conn.records.append((market,stock,"smc"))
            return 74
        with (
            patch.dict(os.environ,{"STOCK_INDICATOR_CATCHUP_WRITE_ENABLED":"yes"}),
            patch.object(ind.psycopg,"connect",return_value=conn),
            patch.object(ind,"build_adjusted_stock",side_effect=adjust),
            patch.object(ind,"calculate_technical_stock",side_effect=technical),
            patch.object(ind,"calculate_smc_stock",side_effect=smc),
        ):
            with self.assertLogs(ind.LOGGER,level="ERROR") as captured:
                results=ind.run("fake",apply=True,per_market=2)
        self.assertEqual([r["status"] for r in results],["failed","verified"])
        self.assertEqual(conn.tx_rolled_back,1)
        self.assertEqual(conn.tx_committed,1)
        self.assertEqual(conn.records,[
            ("tpex","6488","adjusted"),
            ("tpex","6488","technical"),
            ("tpex","6488","smc")
        ])
        self.assertNotIn("PRIVATE-FAILED-DATABASE-OPERATION","\\n".join(captured.output))

    def test_incomplete_verification_rolls_back_both_stocks(self):
        conn=Connection()
        with (
            patch.dict(os.environ,{"STOCK_INDICATOR_CATCHUP_WRITE_ENABLED":"yes"}),
            patch.object(ind.psycopg,"connect",return_value=conn),
            patch.object(ind,"build_adjusted_stock",return_value=74),
            patch.object(ind,"calculate_technical_stock",return_value=74),
            patch.object(ind,"calculate_smc_stock",return_value=5),
        ):
            results=ind.run("fake",apply=True)
        self.assertEqual([r["status"] for r in results],["failed","failed"])
        self.assertEqual(conn.tx_rolled_back,2)
        self.assertEqual(conn.tx_committed,0)

    def test_failure_does_not_print_private_exception_details(self):
        conn=Connection()
        with (
            patch.dict(os.environ,{"STOCK_INDICATOR_CATCHUP_WRITE_ENABLED":"yes"}),
            patch.object(ind.psycopg,"connect",return_value=conn),
            patch.object(ind,"build_adjusted_stock",side_effect=RuntimeError("PRIVATE-DB-TOKEN")),
        ):
            with self.assertLogs(ind.LOGGER,level="ERROR") as captured:
                result=ind.run("fake",apply=True)
        self.assertEqual([x["status"] for x in result],["failed","failed"])
        self.assertTrue(all(x["error_type"]=="RuntimeError" for x in result))
        self.assertNotIn("PRIVATE-DB-TOKEN","\n".join(captured.output))

    def test_incomplete_indicator_outputs_are_not_counted_as_success(self):
        conn=Connection()
        with (
            patch.dict(os.environ,{"STOCK_INDICATOR_CATCHUP_WRITE_ENABLED":"yes"}),
            patch.object(ind.psycopg,"connect",return_value=conn),
            patch.object(ind,"build_adjusted_stock",return_value=74),
            patch.object(ind,"calculate_technical_stock",return_value=50),
            patch.object(ind,"calculate_smc_stock",return_value=74),
        ):
            result=ind.run("fake",apply=True)
        self.assertEqual([x["status"] for x in result],["failed","failed"])
        self.assertTrue(all(x["error_type"]=="RuntimeError" for x in result))


if __name__=="__main__":
    unittest.main()
