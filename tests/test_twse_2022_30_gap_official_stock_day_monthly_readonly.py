"""Synthetic-only tests for owner 30 gap original TWSE monthly price-date presence."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from urllib.parse import urlencode
from unittest.mock import Mock

from scripts.twse_2022_aes_neon_eligible_density_readonly import SCOPE as PARENT_SCOPE
from scripts.twse_2022_30_gap_official_stock_day_monthly_readonly import (
    ENDPOINT, fetch_twse_stock_month, reconcile_official_30,
    validate_owner_30_queue,
)


def frozen_30():
    entries=[
        {"stock_id":str(2000+i),
         "first_unobserved_source_day":"2022-09-07",
         "last_unobserved_source_day":"2022-09-16",
         "unobserved_consecutive_source_days":7,
         "confirmed_official_halt_for_these_dates":False,
         "confirmed_missing_price_repair_obligation":False}
        for i in range(30)
    ]
    return {
        "schema_version":1,"scope":PARENT_SCOPE,"year":2022,
        "official_current_listed_eligible_twse_issuers":1092,
        "aes_plus_neon_unique_observed_source_dates":246,
        "aes_neon_current_listed_stocks_with_all_246_source_dates":825,
        "model_release":"BLOCKED","production_neon_writes":0,
        "line_messages_sent":0,
        "owner_private_all_30_long_source_absence_runs_official_check_queue":{
            "schema_version":1,
            "scope":"OWNER_2022_TWSE_ALL_LONG_SOURCE_ABSENCE_OFFICIAL_CHECK_QUEUE",
            "underlying_116_source_absence_stocks":116,
            "underlying_all_absent_stock_source_day_pairs":804,
            "underlying_all_absent_source_day_runs":526,
            "at_least_six_unobserved_source_day_run_count":30,
            "all_30_long_source_absence_runs_recovered_from_source":True,
            "official_halt_or_resumption_not_checked_by_this_offline_step":True,
            "zero_stock_price_imputation":True,
            "model_release":"BLOCKED","production_neon_writes":0,
            "line_messages_sent":0,
            "owner_private_long_run_official_halt_check_queue":entries,
        }
    }


def official_month(stock,category="valid"):
    req={"response":"json","date":"20220901","stockNo":stock}
    fields=["日期","成交股數","成交金額","開盤價","最高價",
            "最低價","收盤價","漲跌價差","成交筆數"]
    row=["111/09/07","123,450","234,567","15.0",
         "16.0","14.0","15.5","+0.5","100"]
    if category=="outside":
        row[0]="111/09/01"
    if category=="uncertain":
        row[6]="--"
    if category=="wrongmonth":
        row[0]="111/08/03"
    body={"stat":"OK","title":f"111年09月 {stock} 人工合成各日成交資訊",
          "fields":fields,"data":[row]}
    if category=="nodata":
        body={"stat":"很抱歉，沒有符合條件的資料!","data":[]}
    response=Mock()
    response.status_code=200
    response.url=ENDPOINT+"?"+urlencode(req)
    response.content=json.dumps(body,ensure_ascii=False).encode("utf-8")
    response.json.return_value=body
    return response


class TWSE2022OwnerLongGapsOfficialMonthlySyntheticTests(unittest.TestCase):
    def test_frozen30_stock_month_budget_and_four_observation_categories(self):
        receipt=frozen_30()
        rows,req=validate_owner_30_queue(receipt)
        self.assertEqual(len(rows),30)
        self.assertEqual(len(req),30)
        monthly={}
        for sid,month in req:
            cat={"2001":"nodata","2002":"outside","2003":"uncertain"}.get(sid,"valid")
            response=official_month(sid,cat)
            get=Mock(return_value=response)
            proof=fetch_twse_stock_month(sid,month,get=get)
            self.assertEqual(proof["official_response_not_a_halt_certificate"],True)
            self.assertEqual(len(proof["official_response_sha256"]),64)
            get.assert_called_once()
            self.assertFalse(get.call_args.kwargs["allow_redirects"])
            self.assertEqual(get.call_args.kwargs["params"]["date"],"20220901")
            monthly[(sid,month)]=proof
        result=reconcile_official_30(receipt,monthly)
        self.assertEqual(result["official_unique_issuer_month_requests"],30)
        self.assertEqual(result["official_months_with_unverified_no_data_response"],1)
        self.assertEqual(result["official_months_with_dated_rows"],29)
        self.assertEqual(result["classification_counts"],{
            "at_least_one_official_valid_source_row_in_gap_window":27,
            "official_rows_but_unverified_close_in_gap_window":1,
            "no_official_rows_in_gap_window_not_proof_of_halt":1,
            "official_month_no_data_response_cannot_classify":1,
        })
        outcomes={r["stock_id"]:r for r in
                  result["owner_private_official_monthly_date_check_results"]}
        self.assertEqual(outcomes["2000"]["official_valid_source_dates_found_inside_window"],
                         ["2022-09-07"])
        self.assertEqual(outcomes["2002"]["official_valid_source_dates_found_inside_window"],[])
        self.assertEqual(outcomes["2003"]["official_unverified_close_dates_inside_window"],
                         ["2022-09-07"])
        self.assertTrue(result["source_price_values_not_exported"])
        self.assertTrue(result["source_row_absence_does_not_certify_suspension"])
        self.assertFalse(result["official_halt_or_resumption_status_finalized"])
        self.assertEqual(result["production_neon_writes"],0)
        self.assertEqual(result["line_messages_sent"],0)
        self.assertEqual(result["model_release"],"BLOCKED")
        self.assertNotIn("123,450",str(result))
        self.assertNotIn("15.5",str(result))

    def test_frozen30_receipt_changed_extra_ids_or_1589_fail_closed(self):
        receipt=frozen_30()
        for field,val in (("model_release","APPROVED"),
                          ("production_neon_writes",1),
                          ("official_current_listed_eligible_twse_issuers",1090)):
            bad=dict(receipt,**{field:val})
            with self.assertRaises(ValueError):
                validate_owner_30_queue(bad)
        for stock in ("1589","xx12"):
            bad=deepcopy(receipt)
            bad["owner_private_all_30_long_source_absence_runs_official_check_queue"][
                "owner_private_long_run_official_halt_check_queue"][0]["stock_id"]=stock
            with self.assertRaises(ValueError):
                validate_owner_30_queue(bad)
        bad=deepcopy(receipt)
        d=bad["owner_private_all_30_long_source_absence_runs_official_check_queue"][
            "owner_private_long_run_official_halt_check_queue"]
        d[1]=dict(d[0])
        with self.assertRaises(ValueError):
            validate_owner_30_queue(bad)
        bad=deepcopy(receipt)
        bad["owner_private_all_30_long_source_absence_runs_official_check_queue"][
            "owner_private_long_run_official_halt_check_queue"][0][
                "confirmed_official_halt_for_these_dates"]=True
        with self.assertRaises(ValueError):
            validate_owner_30_queue(bad)

    def test_tampered_missing_month_and_duplicate_official_dates_rejected(self):
        original=frozen_30()
        _,req=validate_owner_30_queue(original)
        monthly={(sid,m):fetch_twse_stock_month(
            sid,m,get=Mock(return_value=official_month(sid)))
                 for sid,m in req}
        with self.assertRaises(ValueError):
            reconcile_official_30(original,dict(list(monthly.items())[:-1]))
        bad=deepcopy(monthly)
        bad[req[0]]["official_valid_source_dates"]=["2022-09-07","2022-09-07"]
        with self.assertRaises(ValueError):
            reconcile_official_30(original,bad)
        bad=deepcopy(monthly)
        bad[req[0]]["official_valid_source_dates"]=["2023-09-07"]
        with self.assertRaises(ValueError):
            reconcile_official_30(original,bad)

    def test_wrong_response_host_day_title_payload_and_limit_fail(self):
        for mode in ("redirect","wrongmonth","duplicate","wrongtitle","oversize","wronghost"):
            response=official_month("2001")
            if mode=="redirect":
                response.status_code=302
            elif mode=="wrongmonth":
                response=official_month("2001","wrongmonth")
            elif mode=="duplicate":
                response.json.return_value["data"].append(
                    list(response.json.return_value["data"][0]))
            elif mode=="wrongtitle":
                response.json.return_value["title"]="111年09月 9876 偽造"
            elif mode=="oversize":
                response.content=b"x"*2_000_001
            else:
                response.url="https://untrusted.example.net/source"
            with self.assertRaises(ValueError):
                fetch_twse_stock_month(
                    "2001","2022-09",get=Mock(return_value=response))

    def test_no_data_is_unknown_not_halt_or_missing_price(self):
        response=official_month("2001","nodata")
        proof=fetch_twse_stock_month(
            "2001","2022-09",get=Mock(return_value=response))
        self.assertEqual(proof["official_response_category"],
                         "UNVERIFIED_NO_DATA_RESPONSE")
        self.assertTrue(proof["official_response_not_a_halt_certificate"])
        self.assertEqual(proof["official_valid_source_dates"],[])

    def test_help_has_no_neon_uri_or_aes(self):
        root=Path(__file__).resolve().parents[1]
        env=os.environ.copy()
        for k in ("DATABASE_URL","STOCK_ARCHIVE_KEY_HEX","PYTHONPATH"):
            env.pop(k,None)
        proc=subprocess.run(
            [sys.executable,"-m",
             "scripts.twse_2022_30_gap_official_stock_day_monthly_readonly",
             "--help"],cwd=root,env=env,capture_output=True,text=True,timeout=25)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertIn("--prior-238-report",proc.stdout)
        self.assertIn("--out",proc.stdout)


if __name__=="__main__":
    unittest.main()
