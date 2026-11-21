"""Real disposable PostgreSQL query for frozen full-universe future labels."""
from __future__ import annotations

from datetime import date
import json
import os
from urllib.parse import urlparse
import unittest

import psycopg
from psycopg.rows import dict_row

from src.research_forward_outcome import FROZEN_LABEL_SQL,assess_frozen_outcomes


@unittest.skipUnless(os.getenv("STOCK_CI_POSTGRES_URL"),
                     "Disposable PostgreSQL CI database not present")
class FrozenActualSessionLabelsPostgres(unittest.TestCase):
    def test_real_raw_session_positions_maturity_and_mismatched_dates(self):
        url=os.environ["STOCK_CI_POSTGRES_URL"]
        parsed=urlparse(url)
        self.assertEqual(parsed.hostname,"127.0.0.1")
        self.assertEqual(parsed.path,"/stock_ci_test")
        schema="ci_forward_lbl"
        sql=FROZEN_LABEL_SQL.replace("public.",schema+".")
        roster=[{"market":"twse","stock_id":str(1000+i),
                 "model_rank":i+1,"baseline_rank":50-i}
                for i in range(50)]
        sessions=[date(2026,11,d) for d in (23,24,25,26,27,30)]
        with psycopg.connect(url,row_factory=dict_row) as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("CREATE SCHEMA "+schema)
                    cur.execute("CREATE TABLE "+schema+
                        ".research_forward_frozen_cohorts (model_version text,"
                        "signal_date date,frozen_at timestamptz,"
                        "model_sha256 char(64),cohort_sha256 char(64),"
                        "universe_count integer,selected_count integer,roster jsonb)")
                    cur.execute("CREATE TABLE "+schema+
                        ".daily_prices (market text,stock_id text,"
                        "trade_date date,close numeric(20,4),PRIMARY KEY (market,stock_id,trade_date))")
                    cur.execute("CREATE TABLE "+schema+
                        ".daily_adjusted_prices (market text,stock_id text,"
                        "trade_date date,close numeric(20,4),PRIMARY KEY (market,stock_id,trade_date))")
                    cur.execute("INSERT INTO "+schema+
                        ".research_forward_frozen_cohorts VALUES "
                        "(%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",(
                        "tw-factor-ridge-1",date(2026,11,20),
                        "2026-11-21 05:59:26+00","a"*64,"b"*64,
                        50,10,json.dumps(roster)))
                    data=[("twse",str(1000+i),d,100) for i in range(50) for d in sessions]
                    cur.executemany("INSERT INTO "+schema+
                        ".daily_prices VALUES(%s,%s,%s,%s)",data)
                    adjusted=[("twse",str(1000+i),d,
                               110 if d==date(2026,11,30) else 100)
                              for i in range(50) for d in sessions]
                    cur.executemany("INSERT INTO "+schema+
                        ".daily_adjusted_prices VALUES(%s,%s,%s,%s)",adjusted)

                    def audit(cutoff):
                        cur.execute(sql,("tw-factor-ridge-1",date(2026,11,20),cutoff))
                        result=cur.fetchone()
                        return assess_frozen_outcomes(dict(result),cutoff=cutoff)

                    pre=audit(date(2026,11,20))
                    self.assertEqual(pre["status"],"AWAIT_ENTRY")
                    self.assertEqual(pre["matured_members"],0)
                    entry=audit(date(2026,11,23))
                    self.assertEqual(entry["status"],"AWAIT_SIX_TRADING_SESSIONS")
                    done=audit(date(2026,11,30))
                    self.assertEqual(done["status"],"FULL_COHORT_MATURE_RESEARCH_ONLY")
                    self.assertEqual(done["matured_members"],50)
                    self.assertAlmostEqual(done["model_net_return"],0.097)
                    self.assertAlmostEqual(done["model_net_excess"],-0.003)
                    self.assertFalse(done["live_trading_approved"])

                    cur.execute("UPDATE "+schema+
                        ".daily_adjusted_prices SET close=NULL "
                        "WHERE stock_id='1000' AND trade_date='2026-11-30'")
                    incomplete=audit(date(2026,11,30))
                    self.assertEqual(incomplete["status"],"INCOMPLETE_OFFICIAL_ADJUSTED_LABELS")
                    self.assertIsNone(incomplete["model_net_excess"])
                    cur.execute("UPDATE "+schema+
                        ".daily_adjusted_prices SET close=110 "
                        "WHERE stock_id='1000' AND trade_date='2026-11-30'")
                    cur.execute("DELETE FROM "+schema+
                        ".daily_prices WHERE stock_id='1000' AND trade_date='2026-11-23'")
                    cur.execute("INSERT INTO "+schema+
                        ".daily_prices VALUES('twse','1000','2026-12-01',100)")
                    cur.execute("INSERT INTO "+schema+
                        ".daily_adjusted_prices VALUES('twse','1000','2026-12-01',110)")
                    different=audit(date(2026,12,1))
                    self.assertEqual(different["status"],"UNALIGNED_ACTUAL_ENTRY_EXIT_DATES")
                    self.assertIsNone(different["baseline_net_return"])
            finally:
                conn.rollback()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('ci_forward_lbl.daily_prices')")
                self.assertIsNone(cur.fetchone()[0])


if __name__=="__main__":
    unittest.main()
