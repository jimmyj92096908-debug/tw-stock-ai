"""Official general-industry balance sheet first-observation safeguards."""
from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock,patch

from src import official_balance_sheet_archive as balance
from scripts import capture_official_balance_sheet as archive

AT="2026-11-21T16:30:00+08:00"


def row(stock="2330", assets="10,000", liab="4,000", equity="6,000"):
    return {
       "公司代號":stock,"年度":"115","季別":"3","出表日期":"1151121",
       "資產總計":assets,"負債總計":liab,"權益總計":equity,
       "流動資產":"4,200","流動負債":"2,000",
       "歸屬於母公司業主之權益合計":"5,900",
    }


class OfficialBalanceFirstSeenTests(unittest.TestCase):
    def test_full_accounting_identity_and_exact_period(self):
        item=balance.parse_snapshot("twse",[row()],observed_at=AT)[0]
        self.assertEqual(item["stock_id"],"2330")
        self.assertEqual(item["fiscal_year"],2026)
        self.assertEqual(item["fiscal_quarter"],3)
        self.assertEqual(item["period_end"],"2026-09-30")
        self.assertEqual(item["official_table_date"],"2026-11-21")
        self.assertEqual(item["assets_thousands_ntd"],"10000")
        self.assertEqual(item["liabilities_thousands_ntd"],"4000")
        self.assertEqual(item["equity_thousands_ntd"],"6000")
        self.assertTrue(item["accounting_identity_verified"])
        self.assertEqual(item["first_observed_at"],AT)
        self.assertEqual(len(item["payload_sha256"]),64)
        self.assertNotIn("published_at",item)

    def test_tpex_english_issuer_and_missing_table_date_is_not_fabricated(self):
        x={"Year":"115","Season":"3","SecuritiesCompanyCode":"3523",
           "TotalAssets":"34567","TotalLiabilities":"14567",
           "TotalEquity":"20000","CurrentAssets":"10000"}
        item=balance.parse_snapshot("tpex",[x],observed_at=AT)[0]
        self.assertEqual(item["stock_id"],"3523")
        self.assertIsNone(item["official_table_date"])
        self.assertIsNone(item["current_liabilities_thousands_ntd"])
        self.assertTrue(item["accounting_identity_verified"])
        self.assertEqual(item["source_url"],balance.SOURCES["tpex"])

    def test_real_source_imbalance_is_not_used_for_fundamental_factor(self):
        items=balance.parse_snapshot("twse",[row(equity="4,000")],observed_at=AT)
        self.assertFalse(items[0]["accounting_identity_verified"])
        looked=balance.asof_balance(items,market="twse",stock_id="2330",
                                   signal_cutoff="2026-11-23T13:30:00+08:00")
        self.assertTrue(looked["covered"])
        self.assertFalse(looked["safe_for_ratio_research"])
        self.assertFalse(looked["live_trading_approved"])

    def test_first_observation_prevents_future_information_on_earlier_signal(self):
        versions=balance.parse_snapshot("twse",[row()],observed_at=AT)
        earlier=balance.asof_balance(versions,market="twse",stock_id="2330",
                                    signal_cutoff="2026-11-20T13:30:00+08:00")
        after=balance.asof_balance(versions,market="twse",stock_id="2330",
                                  signal_cutoff="2026-11-23T13:30:00+08:00")
        self.assertIsNone(earlier["balance"])
        self.assertFalse(earlier["covered"])
        self.assertTrue(after["safe_for_ratio_research"])
        self.assertFalse(after["issuer_published_at_known"])
        revised=balance.parse_snapshot("twse",[row(assets="11000",equity="7000")],
                                       observed_at="2026-11-24T18:00:00+08:00")
        self.assertNotEqual(versions[0]["payload_sha256"],revised[0]["payload_sha256"])
        self.assertEqual(
            balance.asof_balance(versions+revised,market="twse",stock_id="2330",
                                 signal_cutoff="2026-11-24T13:30:00+08:00")
            ["balance"]["assets_thousands_ntd"],"10000")
        self.assertEqual(
            balance.asof_balance(versions+revised,market="twse",stock_id="2330",
                                 signal_cutoff="2026-11-25T13:30:00+08:00")
            ["balance"]["assets_thousands_ntd"],"11000")

    def test_bad_dates_duplicates_invalid_amounts_and_missing_all_fail_closed(self):
        for raw in (
            [row(),row()],
            [row(assets="-10")],
            [row(liab="-5")],
            [row(assets="NaN")],
            [row(assets="Infinity")],
            [{**row(),"年度":"116"}],
            [{**row(),"季別":"5"}],
            [{**row(),"出表日期":"1150920"}],
            [row(assets="no number")],
        ):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    balance.parse_snapshot("twse",raw,observed_at=AT)
        with self.assertRaises(ValueError):
            balance.parse_snapshot("twse",[row()],observed_at="2026-11-21T10:00:00")
        with self.assertRaises(ValueError):
            balance.parse_snapshot("twse",[],observed_at=AT)
        with self.assertRaises(ValueError):
            balance.parse_snapshot("twse",[row()]*2501,observed_at=AT)
        with self.assertRaises(ValueError):
            balance.asof_balance([],market="twse",stock_id="2330",
                                 signal_cutoff="2026-11-23T14:00:00+08:00")

    def test_fixed_https_source_and_no_redirect_or_oversized_response(self):
        response=MagicMock(status_code=200,url=balance.SOURCES["twse"],content=b"[]")
        response.json.return_value=[row()]
        client=MagicMock()
        client.get.return_value=response
        items=archive.fetch_official("twse",session=client,observed_at=AT)
        self.assertEqual(len(items),1)
        self.assertFalse(client.get.call_args.kwargs["allow_redirects"])
        self.assertEqual(client.get.call_args.kwargs["timeout"],(10,30))
        response.url="http://invalid.example"
        with self.assertRaises(RuntimeError):
            archive.fetch_official("twse",session=client,observed_at=AT)
        response.url=balance.SOURCES["twse"]
        response.content=b"x"*(archive.MAX_BYTES_PER_SOURCE+1)
        with self.assertRaises(RuntimeError):
            archive.fetch_official("twse",session=client,observed_at=AT)

    def test_no_live_write_without_gate_or_fake_capture_time(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(PermissionError):
                archive.capture("fake",apply=True)
        with patch.dict(os.environ,{"STOCK_OFFICIAL_BALANCE_WRITE":"yes"}):
            with self.assertRaises(ValueError):
                archive.capture("fake",apply=True,observed_at=AT)
        with patch.object(archive,"fetch_official",return_value=balance.parse_snapshot(
                "twse",[row()],observed_at=AT)), \
             patch.object(archive.psycopg,"connect") as connect:
            result=archive.capture("",apply=False,observed_at=AT)
            self.assertFalse(result["persisted"])
            self.assertEqual(result["inserted"],0)
            self.assertFalse(result["cashflow_coverage_approved"])
            connect.assert_not_called()

    def test_insert_is_append_only_known_ticker_and_db_immutable(self):
        stmt=archive.INSERT_SQL.upper()
        self.assertIn("PUBLIC.STOCK_MASTER",stmt)
        self.assertIn("ON CONFLICT (MARKET,STOCK_ID,PERIOD_END,PAYLOAD_SHA256) DO NOTHING",stmt)
        self.assertIn("%(STOCK_ID)S::VARCHAR(6)",stmt)
        self.assertIn("%(MARKET)S::TEXT",stmt)
        self.assertNotIn("DO UPDATE",stmt)
        ddl=(Path(__file__).resolve().parents[1]/
             "sql/official_balance_sheet_observation_schema.sql").read_text()
        self.assertIn("BEFORE UPDATE OR DELETE",ddl)
        self.assertIn("official_balance_immutable",ddl)


if __name__=="__main__":
    unittest.main()
