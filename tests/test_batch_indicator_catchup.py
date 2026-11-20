"""Offline safety tests for gradual 60+ session indicator enrichment."""
import os
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
        }]
    def fetchone(self):
        return {"adjusted_rows":74,"technical_rows":74,"smc_rows":74}


class Connection:
    def __init__(self):self.cur=Cursor()
    def __enter__(self):return self
    def __exit__(self,*_):return False
    def cursor(self):return self.cur


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
        self.assertEqual(conn.cur.calls[1][1],("twse","2330","twse","2330","twse","2330"))

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
