"""Isolated PostgreSQL17 test for bounded prospective snapshot day selection."""
from __future__ import annotations

from datetime import date
import os
from urllib.parse import urlparse
import unittest

import psycopg

from src.frozen_cohort_progress import DATES_SQL


@unittest.skipUnless(os.getenv("STOCK_CI_POSTGRES_URL"),
                     "Disposable localhost PostgreSQL database not available")
class FrozenCohortDateSelectionPostgresTests(unittest.TestCase):
    def test_real_pg_filters_future_unfrozen_dates_and_limits_results(self):
        url=os.environ["STOCK_CI_POSTGRES_URL"]
        parsed=urlparse(url)
        self.assertEqual(parsed.hostname,"127.0.0.1")
        self.assertEqual(parsed.path,"/stock_ci_test")
        sql=DATES_SQL.replace("public.","ci_cohort_progress.")
        with psycopg.connect(url) as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("CREATE SCHEMA ci_cohort_progress")
                    cur.execute("CREATE TABLE ci_cohort_progress.research_forward_frozen_cohorts "
                                "(model_version text,signal_date date)")
                    cur.executemany(
                        "INSERT INTO ci_cohort_progress.research_forward_frozen_cohorts "
                        "VALUES (%s,%s)",
                        [("tw-factor-ridge-1",date(2026,11,20)),
                         ("tw-factor-ridge-1",date(2026,11,23)),
                         ("tw-factor-ridge-1",date(2026,11,24)),
                         ("unapproved-model",date(2026,11,19))])
                    cur.execute(sql,("tw-factor-ridge-1",date(2026,11,23),12))
                    self.assertEqual([r[0].isoformat() for r in cur.fetchall()],
                                     ["2026-11-23","2026-11-20"])
                    cur.execute(sql,("tw-factor-ridge-1",date(2026,11,30),1))
                    self.assertEqual([r[0].isoformat() for r in cur.fetchall()],
                                     ["2026-11-24"])
            finally:
                conn.rollback()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('ci_cohort_progress.research_forward_frozen_cohorts')")
                self.assertIsNone(cur.fetchone()[0])


if __name__=="__main__":
    unittest.main()
