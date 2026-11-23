"""Offline tests for free TWSE current listed company basic listing date source."""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock

from scripts.twse_2022_official_current_listing_date_triage import (
    URL, fetch_official_company_basics,
    classify_official_current_listing,
)


def source_inputs():
    roster=set(str(n) for n in range(1000,2093) if n!=1589)
    assert len(roster)==1092
    zero=set(sorted(roster)[-129:])
    rows=[{"公司代號":sid, "上市日期":"20000202",
           "出表日期":"1151122"} for sid in sorted(roster)]
    first={sid:date(2023,1,3) for sid in roster}
    for i,sid in enumerate(sorted(zero)):
        index=sorted(roster).index(sid)
        if i < 20:
            rows[index]["上市日期"]="20230403"
            first[sid]=date(2023,4,4)
        elif i < 45:
            rows[index]["上市日期"]="20240304"
            first[sid]=date(2024,3,5)
        elif i < 65:
            rows[index]["上市日期"]="20250505"
            first[sid]=date(2025,5,6)
        elif i < 75:
            rows[index]["上市日期"]="20261102"
            first[sid]=date(2026,11,3)
        elif i < 125:
            rows[index]["上市日期"]="20180510"
            first[sid]=date(2023,1,3)
        else:
            rows[index]["上市日期"]=""
            first[sid]=date(2023,1,3)
    proof={"rows":rows,"response_sha256":"a"*64,"endpoint":URL}
    return proof,roster,zero,first


class CurrentTWSEListingDateOwnerAuditSyntheticTests(unittest.TestCase):
    def test_official_current_date_buckets_no_ipo_or_pit_certification(self):
        evidence,roster,zero,first=source_inputs()
        r=classify_official_current_listing(
            evidence,eligible_ids=roster,no_2022_ids=zero,
            first_2023plus=first,current_day=date(2026,11,23),
            prior_window_end=date(2026,11,23))
        self.assertEqual(r["official_current_company_rows"],1092)
        self.assertEqual(r["owner_2022_no_valid_source_stock_count"],129)
        self.assertEqual(r["current_twse_listing_after_2022_count"],75)
        self.assertEqual(r["current_twse_listing_on_or_before_2022_count"],50)
        self.assertEqual(r["current_twse_listing_missing_or_invalid_count"],4)
        self.assertEqual(r["source_metadata_observed_at"],"2026-11-22")
        counts=r["source_listing_date_bucket_counts"]
        self.assertEqual([counts[f"current_twse_listing_date_{year}"]
                          for year in (2023,2024,2025,2026)],
                         [20,25,20,10])
        self.assertEqual(counts[
            "current_2023plus_listing_and_first_stored_not_before_listing_date"],75)
        self.assertEqual(counts[
            "current_2023plus_listing_but_neon_first_stored_before_current_listing_date"],0)
        self.assertTrue(r["current_basic_company_listing_date_is_not_historic_pit_roster"])
        self.assertTrue(r["first_stored_neon_stock_bar_is_not_official_ipo_date"])
        self.assertTrue(r["transfer_relisting_or_earlier_listed_instrument_history_not_certified"])
        self.assertTrue(r["any_early_or_missing_listing_date_requires_further_official_research"])
        self.assertFalse(r["original_historic_listing_or_halt_actions_fully_verified"])
        self.assertTrue(r["absence_never_authorizes_price_imputation"])
        self.assertEqual(r["model_release"],"BLOCKED")
        self.assertEqual(r["production_neon_writes"],0)
        self.assertEqual(r["line_messages_sent"],0)
        self.assertNotIn("stock_id",str(r))
        self.assertNotIn("raw_close",str(r))

    def test_early_stored_neon_before_current_listed_date_is_not_greenwashed(self):
        e,roster,zero,first=source_inputs()
        sid=sorted(zero)[0]
        first[sid]=date(2023,1,3)
        result=classify_official_current_listing(
            e,eligible_ids=roster,no_2022_ids=zero,
            first_2023plus=first,current_day=date(2026,11,23),
            prior_window_end=date(2026,11,23))
        c=result["source_listing_date_bucket_counts"]
        self.assertEqual(c[
            "current_2023plus_listing_but_neon_first_stored_before_current_listing_date"],1)
        self.assertEqual(result["model_release"],"BLOCKED")

    def test_stale_mixed_future_or_duplicate_company_metadata_rejected(self):
        for mode in ("stale","mixed","duplicate","future","invalid_row"):
            e,roster,zero,first=source_inputs()
            if mode=="stale":
                for r in e["rows"]:
                    r["出表日期"]="1151001"
            if mode=="mixed":
                e["rows"][0]["出表日期"]="1151121"
            if mode=="duplicate":
                e["rows"][1]["公司代號"]=e["rows"][0]["公司代號"]
            if mode=="future":
                for r in e["rows"]:
                    r["出表日期"]="1151125"
            if mode=="invalid_row":
                e["rows"][0]="invalid"
            with self.assertRaises(ValueError):
                classify_official_current_listing(
                    e,eligible_ids=roster,no_2022_ids=zero,
                    first_2023plus=first,current_day=date(2026,11,23),
                    prior_window_end=date(2026,11,23))

    def test_current_listing_date_later_than_2026_owner_asof_fails(self):
        e,roster,zero,first=source_inputs()
        stock=sorted(zero)[0]
        for r in e["rows"]:
            if r["公司代號"]==stock:
                r["上市日期"]="20261201"
        with self.assertRaises(ValueError):
            classify_official_current_listing(
                e,eligible_ids=roster,no_2022_ids=zero,
                first_2023plus=first,current_day=date(2026,11,23),
                prior_window_end=date(2026,11,23))

    def test_untrusted_first_source_dates_and_cohort_rejected(self):
        for mode in ("extra_issuer","bad_first","wrong_zero","old_fiveyear"):
            e,roster,zero,first=source_inputs()
            end=date(2026,11,23)
            if mode=="extra_issuer":
                first["0000"]=date(2024,1,2)
            elif mode=="bad_first":
                first[sorted(zero)[0]]=date(2022,7,4)
            elif mode=="wrong_zero":
                zero.pop()
            elif mode=="old_fiveyear":
                end=date(2025,11,23)
            with self.assertRaises(ValueError):
                classify_official_current_listing(
                    e,eligible_ids=roster,no_2022_ids=zero,
                    first_2023plus=first,current_day=date(2026,11,23),
                    prior_window_end=end)

    def test_https_official_only_once_bounded_bytes_and_source_digest(self):
        rows,_,_,_=source_inputs()
        data=json.dumps(rows["rows"],ensure_ascii=False).encode()
        response=Mock()
        response.content=data
        response.url=URL
        response.json.return_value=rows["rows"]
        get=Mock(return_value=response)
        proof=fetch_official_company_basics(get=get)
        self.assertEqual(proof["response_sha256"],sha256(data).hexdigest())
        self.assertEqual(proof["endpoint"],URL)
        get.assert_called_once()
        args,kwargs=get.call_args
        self.assertEqual(args[0],URL)
        self.assertIn("timeout",kwargs)
        response.url="https://unverified.example.org/redirect"
        with self.assertRaises(ValueError):
            fetch_official_company_basics(get=get)
        response.url=URL
        response.content=b"x"*8_000_001
        with self.assertRaises(ValueError):
            fetch_official_company_basics(get=get)

    def test_owner_cli_help_does_not_need_private_aes_or_neon_uri(self):
        root=Path(__file__).resolve().parents[1]
        env=os.environ.copy()
        for secret in ("DATABASE_URL","STOCK_ARCHIVE_KEY_HEX","PYTHONPATH"):
            env.pop(secret,None)
        p=subprocess.run(
            [sys.executable,"-m",
             "scripts.twse_2022_aes_neon_eligible_density_readonly","--help"],
            cwd=root,env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("--post2022-firstseen",p.stdout)
        self.assertIn("--official-current-listing-audit",p.stdout)


if __name__=="__main__":
    unittest.main()
