"""Actual disposable PostgreSQL17 verification of official balance first-seen rows."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse
import unittest

import psycopg

from src.official_balance_sheet_archive import parse_snapshot
from scripts.capture_official_balance_sheet import INSERT_SQL

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.getenv("STOCK_CI_POSTGRES_URL"),
                     "Disposable local PostgreSQL CI database not available")
class OfficialBalancePostgresTests(unittest.TestCase):
    def test_real_typed_insert_duplicate_revision_unknown_ticker_and_write_guard(self):
        uri=os.environ["STOCK_CI_POSTGRES_URL"]
        parsed=urlparse(uri)
        self.assertEqual(parsed.hostname,"127.0.0.1")
        self.assertEqual(parsed.path,"/stock_ci_test")
        schema="ci_balance"
        ddl=(ROOT/"sql/official_balance_sheet_observation_schema.sql").read_text(
            encoding="utf-8").replace("public.",schema+".")
        sql=INSERT_SQL.replace("public.",schema+".")
        data={
            "公司代號":"2330","年度":"115","季別":"3","出表日期":"1151121",
            "資產總計":"10000","負債總計":"4000","權益總計":"6000",
            "流動資產":"3000","流動負債":"1500",
        }
        initial=parse_snapshot("twse",[data],observed_at="2026-11-21T16:30:00+08:00")[0]
        revised=parse_snapshot("twse",[{**data,"資產總計":"12000","權益總計":"8000"}],
                               observed_at="2026-11-24T16:30:00+08:00")[0]
        with psycopg.connect(uri) as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("CREATE SCHEMA "+schema)
                    cur.execute("CREATE TABLE "+schema+
                                ".stock_master (market text,stock_id varchar(6),"
                                "PRIMARY KEY(market,stock_id))")
                    cur.execute("INSERT INTO "+schema+".stock_master VALUES ('twse','2330')")
                    cur.execute(ddl)
                    cur.executemany(sql,[initial])
                    self.assertEqual(cur.rowcount,1)
                    cur.executemany(sql,[initial])
                    self.assertEqual(cur.rowcount,0)
                    cur.executemany(sql,[revised])
                    self.assertEqual(cur.rowcount,1)
                    cur.executemany(sql,[{**initial,"stock_id":"9999"}])
                    self.assertEqual(cur.rowcount,0)
                    cur.execute("SELECT COUNT(*),COUNT(DISTINCT payload_sha256),"
                                "MIN(assets_thousands_ntd),MAX(assets_thousands_ntd) "
                                "FROM "+schema+".official_balance_sheet_observations")
                    count,versions,min_assets,max_assets=cur.fetchone()
                    self.assertEqual((count,versions),(2,2))
                    self.assertEqual(float(min_assets),10000)
                    self.assertEqual(float(max_assets),12000)
                    for statement in (
                        "UPDATE "+schema+".official_balance_sheet_observations "
                        "SET assets_thousands_ntd=99",
                        "DELETE FROM "+schema+".official_balance_sheet_observations",
                    ):
                        with self.assertRaises(psycopg.errors.RaiseException):
                            with conn.transaction():
                                cur.execute(statement)
            finally:
                conn.rollback()
        with psycopg.connect(uri) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('ci_balance.official_balance_sheet_observations')")
                self.assertIsNone(cur.fetchone()[0])


if __name__=="__main__":
    unittest.main()
