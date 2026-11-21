"""Use genuine disposable PostgreSQL 17 to prove no prior-date financial leakage."""
from __future__ import annotations

from datetime import datetime
import os
from urllib.parse import urlparse
import unittest
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from src.official_fundamental_pit_coverage import FUNDAMENTAL_ASOF_SQL, audit_report

TAIPEI=ZoneInfo("Asia/Taipei")


@unittest.skipUnless(os.getenv("STOCK_CI_POSTGRES_URL"),
                     "Disposable localhost 127.0.0.1 PostgreSQL service unavailable")
class FundamentalPITPostgresTests(unittest.TestCase):
    def test_real_three_source_latest_vintages_and_past_unknown_status(self):
        uri=os.environ["STOCK_CI_POSTGRES_URL"]
        u=urlparse(uri)
        self.assertEqual(u.hostname,"127.0.0.1")
        self.assertEqual(u.path,"/stock_ci_test")
        schema="ci_fundpit"
        sql=FUNDAMENTAL_ASOF_SQL.replace("public.",schema+".")
        with psycopg.connect(uri,row_factory=dict_row) as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("CREATE SCHEMA "+schema)
                    cur.execute("CREATE TABLE "+schema+".stock_master (market text,stock_id text)")
                    cur.execute("CREATE TABLE "+schema+".official_quarterly_income_observations "
                                "(market text,stock_id text,period_end date,"
                                "first_observed_at timestamptz,basic_eps_ytd_ntd numeric,"
                                "net_income_ytd_thousands_ntd numeric,payload_sha256 char(64))")
                    cur.execute("CREATE TABLE "+schema+".official_balance_sheet_observations "
                                "(market text,stock_id text,period_end date,"
                                "first_observed_at timestamptz,assets_thousands_ntd numeric,"
                                "liabilities_thousands_ntd numeric,equity_thousands_ntd numeric,"
                                "current_assets_thousands_ntd numeric,"
                                "current_liabilities_thousands_ntd numeric,"
                                "accounting_identity_verified boolean,payload_sha256 char(64))")
                    cur.execute("CREATE TABLE "+schema+".official_revenue_observations "
                                "(market text,stock_id text,period_end date,"
                                "first_observed_at timestamptz,reported_revenue_thousands_ntd numeric,"
                                "payload_sha256 char(64))")
                    companies=[("twse","2330"),("tpex","3523")]
                    cur.executemany("INSERT INTO "+schema+".stock_master VALUES (%s,%s)",companies)
                    earliest="2026-11-21T14:00:00+08:00"
                    for market,stock in companies:
                        cur.execute("INSERT INTO "+schema+
                            ".official_quarterly_income_observations "
                            "VALUES (%s,%s,'2026-09-30',%s,12.2,1000,%s)",
                            (market,stock,earliest,"a"*64))
                        cur.execute("INSERT INTO "+schema+
                            ".official_balance_sheet_observations "
                            "VALUES (%s,%s,'2026-09-30',%s,20000,8000,12000,"
                            "5000,3000,true,%s)",
                            (market,stock,earliest,"b"*64))
                        cur.execute("INSERT INTO "+schema+
                            ".official_revenue_observations "
                            "VALUES (%s,%s,'2026-10-31',%s,5500,%s)",
                            (market,stock,earliest,"c"*64))
                    # A later changed balance revision must remain invisible
                    # to yesterday's PIT report.
                    cur.execute("INSERT INTO "+schema+
                        ".official_balance_sheet_observations "
                        "VALUES ('twse','2330','2026-09-30',"
                        "'2026-11-24T14:00:00+08:00',21000,8000,13000,"
                        "5000,3000,false,%s)",("d"*64,))

                    def report(day):
                        cutoff=datetime.fromisoformat(day+"T13:30:00+08:00")
                        cur.execute(sql,(cutoff,)*6)
                        return audit_report([dict(r) for r in cur.fetchall()],cutoff=cutoff)

                    before=report("2026-11-20")
                    self.assertEqual(before["totals"]["all_three_sources_observed"],0)
                    self.assertEqual(before["totals"]["observed_balance"],0)
                    after=report("2026-11-23")
                    self.assertEqual(after["totals"]["all_three_sources_observed"],2)
                    self.assertEqual(after["totals"]["safe_eps_and_balance"],2)
                    self.assertEqual(after["totals"]["current_ratio_research_possible"],2)
                    self.assertEqual(after["totals"]["accounting_identity_failures"],0)
                    revised=report("2026-11-25")
                    self.assertEqual(revised["totals"]["all_three_sources_observed"],2)
                    self.assertEqual(revised["totals"]["safe_eps_and_balance"],1)
                    self.assertEqual(revised["totals"]["accounting_identity_failures"],1)
                    self.assertFalse(revised["live_trading_approved"])
            finally:
                conn.rollback()
        with psycopg.connect(uri) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('ci_fundpit.stock_master')")
                self.assertIsNone(cur.fetchone()[0])


if __name__=="__main__":
    unittest.main()
