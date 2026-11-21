"""Actual PostgreSQL regression for official-revenue SQL with repeated binds.

Uses only localhost disposable CI postgres. It *never* connects to Neon.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse
import unittest

import psycopg

from src.official_revenue_archive import parse_snapshot
from scripts.capture_official_revenue import INSERT_SQL

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("STOCK_CI_POSTGRES_URL"),
                     "Disposable localhost PostgreSQL is unavailable")
class OfficialRevenuePsycopgIntegration(unittest.TestCase):
    def test_inserts_and_revision_append_without_ambiguous_bind_types(self):
        url=os.environ["STOCK_CI_POSTGRES_URL"]
        u=urlparse(url)
        self.assertEqual(u.hostname,"127.0.0.1")
        self.assertEqual(u.path,"/stock_ci_test")
        source=(ROOT/"sql/official_revenue_observation_schema.sql").read_text(encoding="utf-8")
        schema="ci_revenue_archive"
        ddl=source.replace("public.",schema+".")
        sql=INSERT_SQL.replace("public.",schema+".")
        sample={"公司代號":"2330","資料年月":"11510","出表日期":"1151117",
                "營業收入-當月營收":"100,000",
                "營業收入-去年同月增減(%)":"1.25"}
        record=parse_snapshot("twse",[sample],observed_at="2026-11-21T18:00:00+08:00")[0]
        revised=parse_snapshot("twse",[{**sample,"營業收入-當月營收":"125,000"}],
                               observed_at="2026-11-23T18:00:00+08:00")[0]
        with psycopg.connect(url) as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("CREATE SCHEMA "+schema)
                    cur.execute("CREATE TABLE "+schema+
                                ".stock_master (market TEXT NOT NULL,stock_id VARCHAR(6) NOT NULL,"
                                "PRIMARY KEY(market,stock_id))")
                    cur.execute(ddl)
                    cur.execute("INSERT INTO "+schema+".stock_master VALUES ('twse','2330')")
                    cur.executemany(sql,[record])
                    self.assertEqual(cur.rowcount,1)
                    cur.executemany(sql,[record])
                    self.assertEqual(cur.rowcount,0)
                    cur.executemany(sql,[revised])
                    self.assertEqual(cur.rowcount,1)
                    unknown={**record,"stock_id":"9999"}
                    cur.executemany(sql,[unknown])
                    self.assertEqual(cur.rowcount,0)
                    cur.execute("SELECT count(*),min(first_observed_at)::date,max(first_observed_at)::date "
                                "FROM "+schema+".official_revenue_observations")
                    n,low,high=cur.fetchone()
                    self.assertEqual(n,2)
                    self.assertEqual(low.isoformat(),"2026-11-21")
                    self.assertEqual(high.isoformat(),"2026-11-23")
            finally:
                conn.rollback()  # No schema or fixture survives this isolated test.


if __name__=="__main__":
    unittest.main()
