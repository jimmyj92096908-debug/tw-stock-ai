"""Real official company listing dates, incomplete delistings and dividends must not fake PIT."""
from datetime import date,datetime,timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock,patch
import os

from scripts import official_current_issuer_snapshot as issuer
from scripts import official_dividend_monthly_preview as dividends

ROOT=Path(__file__).resolve().parents[1]
CAPTURE=datetime(2026,11,21,15,30,tzinfo=timezone.utc)

def issuers(market,count=800):
    base=1000 if market=="twse" else 2000
    return [{"公司代號":str(base+i),"公司簡稱":f"Company {i}",
             "產業別":"資訊","上市日期" if market=="twse" else "上櫃日期":"112/02/03"}
            for i in range(count)]

def ex_row(stock="2250",d="115/11/10",cash="2.5",kind="息"):
    return {"證券代號":stock,"除權息日期":d,"除權息前收盤價":"100",
            "除權息參考價":"97.5","權或息":kind,"現金股利":cash}

def reduction(stock="2250",d="115/11/16"):
    return {"股票代號":stock,"恢復買賣日期":d,
            "停止買賣前收盤價":"100","恢復買賣參考價":"125",
            "每仟股換發股數":"800"}

def groups():
    return {
       ("twse","ex",dividends.TWSE_EX_URL):[
           ex_row(stock="1250"),ex_row(stock="1250")],
       ("twse","reduction",dividends.TWSE_REDUCTION_URL):[],
       ("tpex","ex",dividends.TPEX_EX_URL):[ex_row()],
       ("tpex","reduction",dividends.TPEX_REDUCTION_URL):[reduction()]
    }

def pairs():
    return {("twse",str(1000+i)) for i in range(800)} | {
           ("tpex",str(2000+i)) for i in range(800)}

class IssuerEvidenceTests(TestCase):
    def test_roc_and_gregorian_listing_dates(self):
        self.assertEqual(issuer.listing_date("112/02/03"),"2023-02-03")
        self.assertEqual(issuer.listing_date("2023/02/03"),"2023-02-03")
        self.assertEqual(issuer.listing_date("1120203"),"2023-02-03")
        self.assertEqual(issuer.listing_date("20230203"),"2023-02-03")
        self.assertIsNone(issuer.listing_date("--"))
        for bad in ("XX","1900/02/03","113/13/01","2023-04-31"):
            with self.assertRaises(ValueError):
                issuer.listing_date(bad)

    def test_current_api_date_not_historical_delisted_pit(self):
        snap=issuer.build_snapshot(issuers("twse"),issuers("tpex"),
                  captured_at=CAPTURE,master_pairs=pairs())
        self.assertEqual(snap["current_official_issuer_pairs"],1600)
        self.assertEqual(snap["market_counts"]["tpex"][
            "company_rows_with_official_listing_date"],800)
        self.assertEqual(snap["api_missing_today_master_count"],0)
        self.assertFalse(snap["historical_delisted_issuer_population_complete"])
        self.assertFalse(snap["full_historic_point_in_time_investible_universe_approved"])
        self.assertFalse(snap["historical_suspended_or_transferred_issuers_verified"])
        self.assertTrue(snap["cannot_backdate_capture_time"])
        self.assertEqual(snap["records"][0]["current_api_listing_date"],"2023-02-03")
        self.assertEqual(len(snap["payload_sha256"]),64)
        self.assertLess(len(str(snap).encode()),issuer.MAX_REPORT_BYTES)

    def test_duplicate_unverifiable_or_oversized_current_issuer_fails(self):
        with self.assertRaises(ValueError):
            issuer.build_snapshot(issuers("twse")[:20],issuers("tpex"),
                                 captured_at=CAPTURE)
        with self.assertRaises(ValueError):
            issuer.build_snapshot(issuers("twse"),
                                 issuers("tpex")[:-1]+[issuers("tpex")[0]],
                                 captured_at=CAPTURE)
        with self.assertRaises(ValueError):
            issuer.build_snapshot(issuers("twse"),issuers("tpex"),
                                 captured_at=datetime(2026,11,21))

    def test_one_weekly_immutable_insert_only_after_explicit_gate(self):
        snap=issuer.build_snapshot(issuers("twse"),issuers("tpex"),
                                   captured_at=CAPTURE,master_pairs=pairs())
        conn=MagicMock();conn.__enter__.return_value=conn
        conn.execute.return_value.fetchone.return_value={"bytes":490000000}
        with patch.object(issuer.psycopg,"connect",return_value=conn) as db:
            preview=issuer.freeze_weekly("protected",snap,apply=False)
        self.assertFalse(preview["persisted"])
        self.assertEqual(preview["database_writes"],0)
        self.assertEqual(preview["observed_week"],"2026-11-16")
        self.assertIn("default_transaction_read_only=on",
                      db.call_args.kwargs["options"])
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(PermissionError):
                issuer.freeze_weekly("protected",snap,apply=True)

        def sql(query,*args):
            cursor=MagicMock()
            if query==issuer.SIZE_SQL:cursor.fetchone.return_value={"bytes":490000000}
            elif query==issuer.INSERT_SQL:
                cursor.fetchone.return_value={"payload_sha256":snap["payload_sha256"]}
            elif query==issuer.READ_SQL:
                cursor.fetchone.return_value={"payload_sha256":snap["payload_sha256"]}
            return cursor
        conn.execute.side_effect=sql
        with patch.dict(os.environ,{"STOCK_OFFICIAL_ISSUER_EVIDENCE_WRITE":"yes"}),\
             patch.object(issuer.psycopg,"connect",return_value=conn):
            result=issuer.freeze_weekly("protected",snap,apply=True)
        self.assertTrue(result["persisted"])
        self.assertEqual(result["database_writes"],1)
        sql_calls=[x.args[0] for x in conn.execute.call_args_list]
        self.assertIn(issuer.INSERT_SQL,sql_calls)
        self.assertNotIn("UPDATE public.daily_prices",str(sql_calls))
        self.assertNotIn("DELETE FROM public.daily_prices",str(sql_calls))

    def test_cannot_replace_existing_week_with_changed_source(self):
        snap=issuer.build_snapshot(issuers("twse"),issuers("tpex"),
                                   captured_at=CAPTURE,master_pairs=pairs())
        conn=MagicMock();conn.__enter__.return_value=conn
        def sql(query,*args):
            result=MagicMock()
            if query==issuer.SIZE_SQL:result.fetchone.return_value={"bytes":490000000}
            if query==issuer.INSERT_SQL:result.fetchone.return_value=None
            if query==issuer.READ_SQL:
                result.fetchone.return_value={"payload_sha256":"f"*64}
            return result
        conn.execute.side_effect=sql
        with patch.dict(os.environ,{"STOCK_OFFICIAL_ISSUER_EVIDENCE_WRITE":"yes"}),\
             patch.object(issuer.psycopg,"connect",return_value=conn):
            with self.assertRaises(RuntimeError):
                issuer.freeze_weekly("protected",snap,apply=True)

class OfficialDividendResearchTests(TestCase):
    def test_actual_month_feeds_and_reduction_are_not_total_returns(self):
        report=dividends.assess(groups(),start=date(2026,11,1),end=date(2026,11,20),
            observed_at=CAPTURE,current_stocks=pairs(),
            existing_counts=[{"market":"twse","existing_rows":22,"stocks":3},
                             {"market":"tpex","existing_rows":2,"stocks":1}])
        self.assertEqual(report["raw_four_digit_source_events"],4)
        self.assertEqual(report["distinct_candidate_economic_events"],3)
        self.assertEqual(report["duplicate_economic_feed_records"],1)
        self.assertEqual(report["explicit_cash_amount_candidate_rows"],2)
        self.assertEqual(report["outside_today_stock_master_candidates"],0)
        self.assertFalse(report["verified_total_return_labels"])
        self.assertTrue(report["not_full_five_year_issuer_or_dividend_coverage"])
        self.assertTrue(report["raw_price_labels_still_unadjusted"])
        self.assertTrue(report["no_historical_issuer_publication_vintages_in_feed"])
        self.assertEqual(report["permanent_adjusted_price_rows_created"],0)
        self.assertEqual(report["database_writes"],0)

    def test_cash_zero_and_missing_still_never_certify_return(self):
        g=groups()
        g[("tpex","ex",dividends.TPEX_EX_URL)]=[ex_row(cash="0"),ex_row(cash="-")]
        report=dividends.assess(g,start=date(2026,11,1),end=date(2026,11,20),
            observed_at=CAPTURE,current_stocks=pairs(),existing_counts=[])
        self.assertFalse(report["verified_total_return_labels"])
        self.assertTrue(any(r["explicit_cash_dividend_per_share"] is None
                            for r in report["candidates"]))
        self.assertEqual(report["database_writes"],0)

    def test_reject_future_month_bad_cash_and_fake_official_source(self):
        with self.assertRaises(ValueError):
            dividends.fetch_month(date(2026,11,1),date(2027,1,1),fetcher=lambda *a:[])
        with self.assertRaises(ValueError):
            dividends._candidate(ex_row(cash="-100"),
                 market="tpex",kind="ex",source=dividends.TPEX_EX_URL,
                 observed_at=CAPTURE,start=date(2026,11,1),
                 end=date(2026,11,20),current_set=pairs())
        g=groups()
        key=("tpex","ex",dividends.TPEX_EX_URL)
        g[("tpex","ex","https://unverified.example/feed")]=g.pop(key)
        with self.assertRaises(ValueError):
            dividends.assess(g,start=date(2026,11,1),end=date(2026,11,20),
                observed_at=CAPTURE,current_stocks=pairs(),existing_counts=[])

    def test_monthly_fetch_uses_four_real_official_endpoints_and_short_range(self):
        calls=[]
        def fake_fetch(url,params):
            calls.append((url,params))
            return []
        data=dividends.fetch_month(date(2026,11,1),date(2026,11,20),
                                   fetcher=fake_fetch)
        self.assertEqual(len(calls),4)
        self.assertEqual(len(data),4)
        self.assertEqual({x[0] for x in calls},{
            dividends.TWSE_EX_URL,dividends.TWSE_REDUCTION_URL,
            dividends.TPEX_EX_URL,dividends.TPEX_REDUCTION_URL})
        self.assertEqual(calls[0][1]["startDate"],"20261101")

    def test_workflow_is_readonly_default_and_writes_only_whitelisted_weekly_issuer_source(self):
        wf=(ROOT/".github/workflows/official-free-issuer-dividend-evidence.yml").read_text()
        for name in ("  push:","  workflow_run:","  workflow_dispatch:",
          "Taiwan Stock AI - Daily Data",
          "official_current_issuer_snapshot.py",
          "official_dividend_monthly_preview.py",
          "STOCK_OFFICIAL_ISSUER_EVIDENCE_WRITE",
          "sql/official_issuer_weekly_snapshots.sql",
          ".github/official-current-issuer-dividend-one-shot-20261121.txt"):
            self.assertIn(name,wf)
        self.assertNotIn("  schedule:",wf)
        self.assertNotIn("STOCK_TPEX_DATED_HISTORY_WRITE_ENABLED",wf)
        self.assertNotIn("LINE_CHANNEL_ACCESS_TOKEN",wf)
        self.assertNotIn("--apply --market",wf)
