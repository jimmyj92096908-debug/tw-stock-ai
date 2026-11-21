"""Prove immutable future research snapshot behavior on disposable PostgreSQL17."""
from __future__ import annotations
from datetime import date,datetime
import json
import os
from pathlib import Path
from urllib.parse import urlparse
import unittest
from zoneinfo import ZoneInfo

import psycopg

from src.research_forward_freeze import build_frozen_universe
from scripts.freeze_prospective_research import INSERT_SQL,READ_SQL

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.getenv("STOCK_CI_POSTGRES_URL"),
                     "Disposable localhost PostgreSQL integration service not present")
class FrozenCohortPostgresTests(unittest.TestCase):
    def test_first_capture_only_same_date_cannot_replace_or_backdate(self):
        url=os.environ["STOCK_CI_POSTGRES_URL"]
        parsed=urlparse(url)
        self.assertEqual(parsed.hostname,"127.0.0.1")
        self.assertEqual(parsed.path,"/stock_ci_test")
        model=json.loads((ROOT/"models/tw-factor-ridge-1-research.json").read_text())
        rows=[
            {"market":"twse","stock_id":str(1000+i),
             "as_of_date":date(2026,11,20),"signal_close":10+i,
             "total_score":55+i*.1,"coverage_weight":.8,
             "technical_score":60+i*.1,"smc_score":55,
             "short_term_score":59,"swing_score":60,
             "long_term_score":58}
            for i in range(50)
        ]
        frozen=build_frozen_universe(
            rows,model,model_sha256="a"*64,
            as_of=datetime(2026,11,21,12,0,tzinfo=ZoneInfo("Asia/Taipei")),
            latest_market_date=date(2026,11,20))
        sql=INSERT_SQL.replace("public.","ci_forward.")
        read=READ_SQL.replace("public.","ci_forward.")
        ddl=(ROOT/"sql/research_forward_frozen_cohorts.sql").read_text().replace(
            "public.","ci_forward.")
        data={**frozen,"roster":json.dumps(frozen["members"],allow_nan=False)}
        with psycopg.connect(url) as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("CREATE SCHEMA ci_forward")
                    cur.execute(ddl)
                    cur.execute(sql,data)
                    self.assertEqual(cur.rowcount,1)
                    self.assertIsNotNone(cur.fetchone())
                    cur.execute(read,(frozen["model_version"],frozen["signal_date"]))
                    initial=cur.fetchone()
                    self.assertEqual(initial[0].strip(),frozen["cohort_sha256"])
                    self.assertEqual(initial[1].strip(),"a"*64)
                    self.assertEqual(initial[2],50)
                    self.assertGreaterEqual(initial[3].date(),date(2026,11,20))
                    cur.execute(sql,data)
                    self.assertEqual(cur.rowcount,0)
                    self.assertIsNone(cur.fetchone())
                    altered={**data,"cohort_sha256":"b"*64}
                    cur.execute(sql,altered)
                    self.assertEqual(cur.rowcount,0)
                    cur.execute(read,(frozen["model_version"],frozen["signal_date"]))
                    self.assertEqual(cur.fetchone(),initial)
                    for statement in (
                        "UPDATE ci_forward.research_forward_frozen_cohorts "
                        "SET cohort_sha256='c' WHERE signal_date='2026-11-20'",
                        "DELETE FROM ci_forward.research_forward_frozen_cohorts "
                        "WHERE signal_date='2026-11-20'",
                    ):
                        with self.assertRaises(psycopg.errors.RaiseException):
                            with conn.transaction():
                                cur.execute(statement)
                    cur.execute(
                        "SELECT count(*),jsonb_array_length(roster) "
                        "FROM ci_forward.research_forward_frozen_cohorts GROUP BY roster"
                    )
                    self.assertEqual(cur.fetchone(),(1,50))
            finally:
                conn.rollback()
        # Reproducibility assertion: the disposable schema never persists.
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('ci_forward.research_forward_frozen_cohorts')")
                self.assertIsNone(cur.fetchone()[0])


if __name__=="__main__":
    unittest.main()
