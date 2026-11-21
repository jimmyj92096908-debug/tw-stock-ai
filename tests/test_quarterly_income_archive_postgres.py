"""Actual isolated PostgreSQL17 quarterly first-observed ingestion test."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse
import unittest

import psycopg

from src.official_quarterly_income_archive import parse_snapshot
from scripts.capture_official_quarterly_income import INSERT_SQL

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.getenv("STOCK_CI_POSTGRES_URL"),
                     "CI disposable 127.0.0.1 PostgreSQL connection not present")
class QuarterlySourcePostgresTests(unittest.TestCase):
    def test_real_sql_insert_revision_no_overwrite_unknown_issuer_and_protect_mutation(self):
        url=os.environ["STOCK_CI_POSTGRES_URL"]
        x=urlparse(url)
        self.assertEqual(x.hostname,"127.0.0.1")
        self.assertEqual(x.path,"/stock_ci_test")
        schema="ci_quarter"
        ddl=(ROOT/"sql/official_quarterly_income_observation_schema.sql").read_text().replace(
            "public.",schema+".")
        sql=INSERT_SQL.replace("public.",schema+".")
        source={
            "公司代號":"2330","年度":"115","季別":"3","出表日期":"1151121",
            "營業收入":"1,000,000","營業利益（損失）":"123456",
            "本期淨利（淨損）":"-12345","基本每股盈餘（元）":"12.25",
        }
        first=parse_snapshot("twse",[source],observed_at="2026-11-21T17:00:00+08:00")[0]
        second=parse_snapshot("twse",[{**source,"基本每股盈餘（元）":"13.05"}],
                              observed_at="2026-11-23T17:00:00+08:00")[0]
        with psycopg.connect(url) as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("CREATE SCHEMA "+schema)
                    cur.execute("CREATE TABLE "+schema+".stock_master (market TEXT,stock_id VARCHAR(6),PRIMARY KEY(market,stock_id))")
                    cur.execute("INSERT INTO "+schema+".stock_master VALUES ('twse','2330')")
                    cur.execute(ddl)
                    cur.executemany(sql,[first])
                    self.assertEqual(cur.rowcount,1)
                    cur.executemany(sql,[first])
                    self.assertEqual(cur.rowcount,0)
                    cur.executemany(sql,[second])
                    self.assertEqual(cur.rowcount,1)
                    cur.executemany(sql,[{**first,"stock_id":"9999"}])
                    self.assertEqual(cur.rowcount,0)
                    cur.execute("SELECT count(*),COUNT(DISTINCT payload_sha256),"
                                "MIN(basic_eps_ytd_ntd),MAX(basic_eps_ytd_ntd) "
                                "FROM "+schema+".official_quarterly_income_observations")
                    count,unique,lo,hi=cur.fetchone()
                    self.assertEqual(count,2)
                    self.assertEqual(unique,2)
                    self.assertEqual(float(lo),12.25)
                    self.assertEqual(float(hi),13.05)
                    for mutation in (
                        "UPDATE "+schema+".official_quarterly_income_observations SET basic_eps_ytd_ntd=99",
                        "DELETE FROM "+schema+".official_quarterly_income_observations",
                    ):
                        with self.assertRaises(psycopg.errors.RaiseException):
                            with conn.transaction():
                                cur.execute(mutation)
            finally:
                conn.rollback()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('ci_quarter.official_quarterly_income_observations')")
                self.assertIsNone(cur.fetchone()[0])


if __name__=="__main__":
    unittest.main()
