"""No-secrets offline regression for owner PR239 two unpriced TWSE source gaps."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock
from urllib.parse import urlencode

from scripts.twse_2022_30_gap_official_stock_day_monthly_readonly import (
    SCOPE as PREVIOUS_SCOPE,
)
from scripts.twse_2022_2_unpriced_gap_daily_mi_index_readonly import (
    URL, fetch_official_all_stock_source_day,
    validate_prior_owner_uncertain_monthly_report,
    reconcile_two_unpriced_windows,
)


def original_owner_two():
    records=[]
    for i in range(30):
        stock=f"{2000+i}"
        has_bad=i<2
        d="2022-03-10" if i==0 else "2022-08-11"
        records.append({
            "stock_id":stock,
            "first_unobserved_source_day":
                "2022-03-10" if i==0 else "2022-08-11",
            "last_unobserved_source_day":
                "2022-03-22" if i==0 else "2022-08-19",
            "unobserved_consecutive_source_days":9 if i==0 else 7,
            "official_valid_source_dates_found_inside_window":[],
            "official_unverified_close_dates_inside_window":
                [d] if has_bad else [],
            "official_source_month_provenance":[{
                "month":d[:7],
                "official_response_category":"OFFICIAL_MONTH_RETURNED_DATED_ROWS",
                "official_response_sha256":"a"*64,
            }],
            "observation_classification":
                "official_rows_but_unverified_close_in_gap_window"
                if has_bad else
                "no_official_rows_in_gap_window_not_proof_of_halt",
            "confirmed_formal_halt":False,
            "confirmed_data_fetch_gap_requiring_neon_backfill":False,
        })
    return {
        "schema_version":1,
        "scope":PREVIOUS_SCOPE,
        "prior_authenticated_2022_30_long_source_gap_count":30,
        "prior_authenticated_2022_116_internal_absence_stock_count":116,
        "prior_authenticated_2022_all_804_unobserved_stock_source_dates":804,
        "official_unique_issuer_month_requests":40,
        "classification_counts":{
            "at_least_one_official_valid_source_row_in_gap_window":0,
            "official_rows_but_unverified_close_in_gap_window":2,
            "no_official_rows_in_gap_window_not_proof_of_halt":28,
            "official_month_no_data_response_cannot_classify":0,
        },
        "owner_private_official_monthly_date_check_results":records,
        "model_release":"BLOCKED",
        "production_neon_writes":0,
        "line_messages_sent":0,
        "no_automatic_price_gap_filling_or_deleting":True,
        "source_row_absence_does_not_certify_suspension":True,
    }


def daily_response(day,stock,close="12.5",status="OK"):
    params={"response":"json","date":day.strftime("%Y%m%d"),
            "type":"ALLBUT0999"}
    fields=["證券代號","證券名稱","成交股數",
            "成交筆數","成交金額","開盤價","最高價",
            "最低價","收盤價","漲跌價差"]
    rows=[[stock,"合成股票","10,000","42","100,000",
           "12.4","12.8","12.3",close,"+0.1"]]
    body={"stat":status,"tables":[{"fields":fields,"data":rows}]}
    r=Mock()
    r.status_code=200
    r.url=URL+"?"+urlencode(params)
    r.content=json.dumps(body,ensure_ascii=False).encode("utf-8")
    r.json.return_value=body
    return r


class TwoUnpricedGapBulkDailyCheckTests(unittest.TestCase):
    def test_exact_owner_pr239_receipt_extracts_only_two_date_pairs(self):
        prior=original_owner_two()
        entries,days=validate_prior_owner_uncertain_monthly_report(prior)
        self.assertEqual(entries,[
            ("2000",date(2022,3,10)),
            ("2001",date(2022,8,11))])
        self.assertEqual(days,[date(2022,3,10),date(2022,8,11)])
        self.assertEqual(len(prior[
            "owner_private_official_monthly_date_check_results"]),30)

    def test_daily_mi_index_only_returns_source_stock_close_presence_not_price(self):
        day=date(2022,3,10)
        for close,expected in (
            ("12.5","VALID_POSITIVE_CLOSE"),
            ("--","LISTED_BUT_UNPRICED_OR_UNVERIFIABLE"),
        ):
            reply=daily_response(day,"2000",close=close)
            get=Mock(return_value=reply)
            result=fetch_official_all_stock_source_day(day,get=get)
            self.assertEqual(result["per_issuer"]["2000"],expected)
            self.assertEqual(len(result["sha256"]),64)
            get.assert_called_once()
            self.assertFalse(get.call_args.kwargs["allow_redirects"])
            self.assertEqual(get.call_args.kwargs["params"]["date"],"20220310")
            self.assertNotIn("12.5",str(result))
            self.assertNotIn("10,000",str(result))

    def test_independent_daily_two_dates_reconciliation_never_authorizes_halt(self):
        previous=original_owner_two()
        a=fetch_official_all_stock_source_day(
            date(2022,3,10),
            get=Mock(return_value=daily_response(
                date(2022,3,10),"2000",close="--")))
        b=fetch_official_all_stock_source_day(
            date(2022,8,11),
            get=Mock(return_value=daily_response(
                date(2022,8,11),"2005",close="33.1")))
        result=reconcile_two_unpriced_windows(
            previous,{date(2022,3,10):a,date(2022,8,11):b})
        self.assertEqual(result["independent_official_market_daily_requests"],2)
        self.assertEqual(result[
            "individual_unpriced_official_stock_day_dates_to_crosscheck"],2)
        self.assertEqual(result["source_date_observation_classes"],{
            "LISTED_BUT_UNPRICED_OR_UNVERIFIABLE":1,
            "MI_INDEX_NO_STOCK_ROW_NOT_PROOF_OF_HALT":1,
        })
        self.assertTrue(result["no_halt_or_backfill_authorization"])
        self.assertFalse(result["individual_ohlcv_or_total_return_certified"])
        self.assertEqual(result["model_release"],"BLOCKED")
        self.assertEqual(result["neon_reads"],0)
        self.assertEqual(result["production_neon_writes"],0)
        self.assertEqual(result["line_messages_sent"],0)
        self.assertEqual(len(result["owner_private_second_source_daily_date_checks"]),2)

    def test_official_bulk_non_ok_remains_unresolved(self):
        d=date(2022,3,10)
        x=fetch_official_all_stock_source_day(
            d,get=Mock(return_value=daily_response(
                d,"2000",status="沒有資料")))
        self.assertEqual(x["status"],"NON_OK")
        p=original_owner_two()
        a=fetch_official_all_stock_source_day(
            date(2022,8,11),
            get=Mock(return_value=daily_response(
                date(2022,8,11),"2001")))
        result=reconcile_two_unpriced_windows(
            p,{d:x,date(2022,8,11):a})
        self.assertEqual(result["source_date_observation_classes"],{
            "MI_INDEX_DAY_RESPONSE_NOT_VERIFIABLE":1,
            "VALID_POSITIVE_CLOSE":1,
        })
        self.assertTrue(result["no_halt_or_backfill_authorization"])

    def test_forged_previous_status_count_or_mismatch_row_rejected(self):
        p=original_owner_two()
        for field,value in (
            ("model_release","APPROVED"),
            ("production_neon_writes",1),
            ("scope","FAKE"),
            ("official_unique_issuer_month_requests",100),
        ):
            bad=dict(p,**{field:value})
            with self.assertRaises(ValueError):
                validate_prior_owner_uncertain_monthly_report(bad)
        bad=deepcopy(p)
        bad["owner_private_official_monthly_date_check_results"][0][
            "official_unverified_close_dates_inside_window"]=[]
        with self.assertRaises(ValueError):
            validate_prior_owner_uncertain_monthly_report(bad)
        bad=deepcopy(p)
        bad["owner_private_official_monthly_date_check_results"][0][
            "stock_id"]="1589"
        with self.assertRaises(ValueError):
            validate_prior_owner_uncertain_monthly_report(bad)
        bad=deepcopy(p)
        bad["owner_private_official_monthly_date_check_results"][0][
            "official_unverified_close_dates_inside_window"]=["2021-03-10"]
        with self.assertRaises(ValueError):
            validate_prior_owner_uncertain_monthly_report(bad)

    def test_rejects_untrusted_host_wrong_date_or_duplicate_market_record(self):
        day=date(2022,3,10)
        for mode in ("wrong-host","redirect","wrong-day","duplicate",
                     "oversize","no-stock-table"):
            r=daily_response(day,"2000")
            if mode=="wrong-host":
                r.url="https://evil.test/api"
            elif mode=="redirect":
                r.status_code=302
            elif mode=="wrong-day":
                r.url=r.url.replace("20220310","20220311")
            elif mode=="duplicate":
                body=r.json.return_value
                body["tables"][0]["data"].append(
                    list(body["tables"][0]["data"][0]))
            elif mode=="oversize":
                r.content=b"x"*12_000_001
            else:
                r.json.return_value["tables"][0]["fields"]=["日期"]
            with self.assertRaises(ValueError):
                fetch_official_all_stock_source_day(
                    day,get=Mock(return_value=r))

    def test_original_cli_no_credential_requirement(self):
        env=os.environ.copy()
        for secret in ("DATABASE_URL","STOCK_ARCHIVE_KEY_HEX","PYTHONPATH"):
            env.pop(secret,None)
        proc=subprocess.run(
            [sys.executable,"-m",
             "scripts.twse_2022_2_unpriced_gap_daily_mi_index_readonly",
             "--help"],cwd=Path(__file__).resolve().parents[1],
            capture_output=True,text=True,timeout=20,env=env)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertIn("--prior-239-month-report",proc.stdout)
        self.assertIn("--out",proc.stdout)


if __name__=="__main__":
    unittest.main()
