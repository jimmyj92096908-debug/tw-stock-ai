"""General-industry official quarterly income first-seen and EPS unit tests."""
from __future__ import annotations

from pathlib import Path
import os
import unittest
from unittest.mock import MagicMock,patch

from src import official_quarterly_income_archive as q
from scripts import capture_official_quarterly_income as capture

AT="2026-11-21T17:30:00+08:00"


def twse(stock="2330",eps="12.34",revenue="1234567"):
    return {
        "出表日期":"1151121","年度":"115","季別":"3",
        "公司代號":stock,"營業收入":revenue,
        "營業利益（損失）":"3456.00","本期淨利（淨損）":"1234.00",
        "基本每股盈餘（元）":eps,
    }


class FirstSeenQuarterlySourceTests(unittest.TestCase):
    def test_real_twse_column_names_and_ytd_eps_not_single_quarter(self):
        out=q.parse_snapshot("twse",[twse()],observed_at=AT)
        self.assertEqual(len(out),1)
        rec=out[0]
        self.assertEqual(rec["fiscal_year"],2026)
        self.assertEqual(rec["fiscal_quarter"],3)
        self.assertEqual(rec["period_end"],"2026-09-30")
        self.assertEqual(rec["official_table_date"],"2026-11-21")
        self.assertEqual(rec["basic_eps_ytd_ntd"],"12.34")
        self.assertEqual(rec["revenue_ytd_thousands_ntd"],"1234567")
        self.assertEqual(rec["first_observed_at"],AT)
        self.assertEqual(rec["source_url"],q.SOURCES["twse"])
        self.assertEqual(len(rec["payload_sha256"]),64)
        self.assertNotIn("published_at",rec)

    def test_tpex_mixed_aliases_without_inventing_publication_date(self):
        row={
            "Year":"115","Season":"3","SecuritiesCompanyCode":"3523",
            "營業收入":"123,456","基本每股盈餘（元）":"-1.25",
            "本期淨利（淨損）":"-5000",
        }
        rec=q.parse_snapshot("tpex",[row],observed_at=AT)[0]
        self.assertEqual(rec["stock_id"],"3523")
        self.assertEqual(rec["fiscal_year"],2026)
        self.assertEqual(rec["official_table_date"],None)
        self.assertEqual(rec["basic_eps_ytd_ntd"],"-1.25")
        self.assertEqual(rec["net_income_ytd_thousands_ntd"],"-5000")

    def test_first_observed_cutoff_prevents_historical_eps_leakage(self):
        data=q.parse_snapshot("twse",[twse()],observed_at=AT)
        prior=q.asof_quarterly(data,market="twse",stock_id="2330",
                              signal_cutoff="2026-11-21T13:30:00+08:00")
        after=q.asof_quarterly(data,market="twse",stock_id="2330",
                              signal_cutoff="2026-11-23T13:30:00+08:00")
        self.assertFalse(prior["covered"])
        self.assertIsNone(prior["quarterly_income"])
        self.assertTrue(after["covered"])
        self.assertFalse(after["company_publication_timestamp_known"])
        self.assertFalse(after["financial_factors_added_to_production_model"])
        self.assertFalse(after["live_trading_approved"])

    def test_revisions_append_with_new_hash_without_rewriting_earlier_version(self):
        first=q.parse_snapshot("twse",[twse()],observed_at=AT)
        later=q.parse_snapshot("twse",[twse(eps="15.00")],
                               observed_at="2026-11-23T19:00:00+08:00")
        self.assertNotEqual(first[0]["payload_sha256"],later[0]["payload_sha256"])
        earlier=q.asof_quarterly(first+later,market="twse",stock_id="2330",
                                 signal_cutoff="2026-11-23T13:30:00+08:00")
        after=q.asof_quarterly(first+later,market="twse",stock_id="2330",
                               signal_cutoff="2026-11-24T13:30:00+08:00")
        self.assertEqual(earlier["quarterly_income"]["basic_eps_ytd_ntd"],"12.34")
        self.assertEqual(after["quarterly_income"]["basic_eps_ytd_ntd"],"15.00")

    def test_fail_closed_source_dates_duplicates_future_period_and_nonfinite(self):
        cases=[
            [twse(),twse()],
            [twse(eps="NaN")],
            [twse(eps="Infinity")],
            [{**twse(),"出表日期":"1150915"}],
            [{**twse(),"年度":"116"}],
            [{**twse(),"季別":"5"}],
            [{**twse(),"營業收入":"nope"}],
        ]
        for rows in cases:
            with self.subTest(rows=rows):
                with self.assertRaises(ValueError):
                    q.parse_snapshot("twse",rows,observed_at=AT)
        with self.assertRaises(ValueError):
            q.parse_snapshot("tpex",[],observed_at=AT)
        with self.assertRaises(ValueError):
            q.parse_snapshot("twse",[twse()]*2501,observed_at=AT)
        with self.assertRaises(ValueError):
            q.parse_snapshot("twse",[twse()],observed_at="2026-11-21T13:30:00")
        with self.assertRaises(ValueError):
            q.asof_quarterly([],market="twse",stock_id="2330",
                             signal_cutoff="2026-11-23T15:00:00+08:00")

    def test_eps_extreme_suppressed_without_replacing_actual_revenue(self):
        out=q.parse_snapshot("twse",[twse(eps="1000000")],observed_at=AT)
        self.assertEqual(out[0]["basic_eps_ytd_ntd"],None)
        self.assertTrue(out[0]["eps_outlier_suppressed"])
        self.assertEqual(out[0]["revenue_ytd_thousands_ntd"],"1234567")

    def test_https_allowlist_redirect_content_size_and_explicit_write_gate(self):
        response=MagicMock(
            status_code=200,url=q.SOURCES["twse"],content=b"[]")
        response.json.return_value=[twse()]
        session=MagicMock()
        session.get.return_value=response
        out=capture.fetch("twse",observed_at=AT,session=session)
        self.assertEqual(len(out),1)
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])
        response.url="https://untrusted.example"
        with self.assertRaises(RuntimeError):
            capture.fetch("twse",observed_at=AT,session=session)
        response.url=q.SOURCES["twse"]
        response.content=b"x"*(capture.MAX_SOURCE_BYTES+1)
        with self.assertRaises(RuntimeError):
            capture.fetch("twse",observed_at=AT,session=session)
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(PermissionError):
                capture.capture("fake",apply=True)
        with patch.dict(os.environ,{"STOCK_QUARTERLY_SOURCE_ARCHIVE_WRITE":"yes"}):
            with self.assertRaises(ValueError):
                capture.capture("fake",apply=True,observed_at=AT)

    def test_source_sql_requires_only_known_stock_master_and_append_only(self):
        sql=capture.INSERT_SQL.upper()
        self.assertIn("ON CONFLICT (MARKET,STOCK_ID,PERIOD_END,PAYLOAD_SHA256) DO NOTHING",sql)
        self.assertIn("PUBLIC.STOCK_MASTER",sql)
        self.assertIn("%(STOCK_ID)S::VARCHAR(6)",sql)
        self.assertIn("%(MARKET)S::TEXT",sql)
        self.assertNotIn("DO UPDATE",sql)
        ddl=(Path(__file__).resolve().parents[1]/
              "sql/official_quarterly_income_observation_schema.sql").read_text()
        self.assertIn("quarterly_income_immutable",ddl)
        self.assertIn("BEFORE UPDATE OR DELETE",ddl)


if __name__=="__main__":
    unittest.main()
