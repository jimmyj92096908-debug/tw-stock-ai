"""Offline synthetic zero-source 2021 current TWSE issuer listing-date triage."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import os
from pathlib import Path
import subprocess
import sys
import unittest

from scripts.twse_2021_28day_aes_neon_stockdate_union_readonly import (
    evaluate_2021_union,
)
from scripts.twse_2021_153_zero_source_current_listing_triage import (
    SCOPE, classify_2021_current_listing_dates,
)
from scripts.twse_2022_official_current_listing_date_triage import URL
from tests.test_twse_2021_28day_aes_neon_stockdate_union_readonly import (
    frozen_owner_2021,
)


def fake_owner_153():
    old5,old241,roster,aes,_=frozen_owner_2021()
    dates=sorted(aes)
    neon=[]
    for i,day in enumerate(dates):
        count=20 if i<20 else 19
        for sid in roster[:count]:
            neon.append((day,sid,"TWSE_STOCK_DAY"))
    assert len(neon)==552
    old243=evaluate_2021_union(
        prior_aes=old241,prior_neon=old5,
        recomputed_aes=old241,roster=roster,
        aes_by_day=aes,neon_rows=neon)
    assert old243["actual_deduplicated_aes_neon_stock_date_pairs"]==26120
    assert old243["current_stocks_with_no_source_day_in_2021"]==153
    missing=list(roster[939:])
    assert len(missing)==153
    category_date=(
        [("20211101",5),("20211215",4),("20211231",3),
         ("20220501",10),("20230801",20),("20240101",30),
         ("20250601",40),("20260601",40),("",1)])
    values=[v for v,count in category_date for _ in range(count)]
    assert len(values)==153
    missing_dates=dict(zip(missing,values))
    official={
        "endpoint":URL,
        "response_sha256":"a"*64,
        "rows":[{
            "公司代號":sid,"出表日期":"1151123",
            "上市日期":missing_dates.get(sid,"20200101")
        } for sid in roster],
    }
    return old243,roster,aes,neon,official


class TWSE153ZeroSourceListingDateOwnerOfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owner=fake_owner_153()

    def run_case(self,**overrides):
        prior,roster,aes,neon,official=self.owner
        p=dict(previous_union=prior,current_roster=roster,aes_by_day=aes,
               neon_rows=neon,official_basics=official,
               current_day=date(2026,11,23))
        p.update(overrides)
        return classify_2021_current_listing_dates(**p)

    def test_153_current_listing_dates_segmented_no_ipo_or_halt_certified(self):
        r=self.run_case()
        self.assertEqual(r["scope"],SCOPE)
        self.assertEqual(r["prior_revalidated_2021_aes_neon_deduplicated_stock_date_pairs"],26120)
        self.assertEqual(r["no_2021_aes_or_neon_source_issuer_count"],153)
        self.assertEqual(r["authenticated_2021_source_days"],28)
        buckets=r["current_listing_year_and_period_bucket_counts"]
        self.assertEqual(buckets,{
            "current_listing_on_or_before_first_2021_source_day":5,
            "current_listing_between_first_and_last_2021_source_days":4,
            "current_listing_after_last_2021_source_day_in_2021":3,
            "current_listing_in_2022":10,
            "current_listing_in_2023":20,
            "current_listing_in_2024":30,
            "current_listing_in_2025":40,
            "current_listing_in_2026":40,
            "current_listing_date_missing_or_invalid":1,
        })
        self.assertEqual(r["zero_source_2021_prioritize_manual_historical_listing_research"],10)
        self.assertEqual(len(r[
            "owner_private_153_zero_source_current_stock_listing_date_rows"]),153)
        self.assertFalse(r["official_historic_listing_or_trading_obligation_verified"])
        self.assertTrue(r["otc_transfer_relisting_board_conversion_possible"])
        self.assertTrue(r["zero_price_imputation_or_deleted_source_bars"])
        self.assertEqual(r["production_neon_writes"],0)
        self.assertEqual(r["line_messages_sent"],0)
        self.assertEqual(r["model_release"],"BLOCKED")
        self.assertNotIn("price_open",str(r))
        self.assertNotIn("stock_close",str(r))

    def test_snapshot_wrong_date_duplicate_official_code_or_future_listing_fails(self):
        old,roster,aes,neon,basic=self.owner
        old_basic=deepcopy(basic)
        old_basic["rows"][0]["出表日期"]="1151101"
        with self.assertRaises(ValueError):
            self.run_case(official_basics=old_basic)
        malformed=deepcopy(basic)
        malformed["rows"][1]["公司代號"]=malformed["rows"][0]["公司代號"]
        with self.assertRaises(ValueError):
            self.run_case(official_basics=malformed)
        malformed=deepcopy(basic)
        malformed["rows"][0]["出表日期"]="1151124"
        with self.assertRaises(ValueError):
            self.run_case(official_basics=malformed)
        malformed=deepcopy(basic)
        zero=roster[939]
        for row in malformed["rows"]:
            if row["公司代號"]==zero:
                row["上市日期"]="20270101"
        with self.assertRaises(ValueError):
            self.run_case(official_basics=malformed)

    def test_old_2021_dedup_receipt_zero_cohort_and_bad_1589_rejected(self):
        p,roster,aes,neon,basic=self.owner
        changed=deepcopy(p)
        changed["aes_neon_overlapping_source_stock_date_pairs"]=551
        with self.assertRaises(ValueError):
            self.run_case(previous_union=changed)
        changed=deepcopy(p)
        changed["model_release"]="APPROVED"
        with self.assertRaises(ValueError):
            self.run_case(previous_union=changed)
        with self.assertRaises(ValueError):
            self.run_case(current_roster=(*roster,"1589"))
        invalid={d:set(stocks) for d,stocks in aes.items()}
        invalid[sorted(invalid)[0]].add("1589")
        with self.assertRaises(ValueError):
            self.run_case(aes_by_day=invalid)
        changed=list(neon)
        changed[0]=(changed[0][0],"1589","TWSE_STOCK_DAY")
        with self.assertRaises(ValueError):
            self.run_case(neon_rows=changed)

    def test_no_false_price_gap_even_when_current_listing_earlier_than_2021(self):
        r=self.run_case()
        rows=r["owner_private_153_zero_source_current_stock_listing_date_rows"]
        early=[item for item in rows if
               item["current_listing_date_category"]==
               "current_listing_on_or_before_first_2021_source_day"]
        self.assertEqual(len(early),5)
        self.assertTrue(all(not item[
            "historical_2021_listing_or_trading_obligation_proven"] for item in early))
        self.assertTrue(all(not item["price_repair_or_deletion_authorized"]
                            for item in early))

    def test_owning_machine_cli_not_requiring_secrets_in_github_ci(self):
        env=os.environ.copy()
        for key in ("DATABASE_URL","STOCK_ARCHIVE_KEY_HEX","PYTHONPATH"):
            env.pop(key,None)
        proc=subprocess.run(
            [sys.executable,"-m",
             "scripts.twse_2021_153_zero_source_current_listing_triage",
             "--help"],cwd=Path(__file__).resolve().parents[1],
            env=env,capture_output=True,text=True,timeout=25)
        self.assertEqual(proc.returncode,0,proc.stderr)
        for flag in ("--prior-241-aes-report",
                     "--prior-243-union-report",
                     "--prior-five-year-neon-report","--out"):
            self.assertIn(flag,proc.stdout)


if __name__=="__main__":
    unittest.main()
