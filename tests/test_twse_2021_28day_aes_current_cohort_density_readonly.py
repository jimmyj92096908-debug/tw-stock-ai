"""2021 28-day owner AES current-listed TWSE density, synthetic no-secrets tests."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import os
from pathlib import Path
import subprocess
import sys
import unittest

from scripts.twse_2021_owner_local_fast_archive import ALL_2021_DAYS
from scripts.twse_2021_28day_aes_current_cohort_density_readonly import (
    SCOPE, evaluate_2021_aes_current_cohort, verify_previous_baseline,
)
from scripts.twse_tpex_five_year_neon_only_cohort_readonly import (
    SCOPE as FIVE_YEAR_SCOPE,
)


def baseline():
    return {
        "schema_version":1,
        "scope":FIVE_YEAR_SCOPE,
        "window_start_inclusive":"2021-11-23",
        "window_end_exclusive":"2026-11-23",
        "current_listed_issuers_only_not_historical_pit_membership":True,
        "owner_aes_2021_2022_source_not_included":True,
        "model_release":"BLOCKED",
        "production_neon_writes":0,
        "line_messages_sent":0,
        "market":{
            "twse":{
                "official_current_listed_stocks_excluding_1589":1092,
                "yearly_neon_source_observations":[{
                    "year":2021,
                    "days_with_any_neon_eligible_source_bars":28,
                    "days_with_at_least_500_eligible_source_bars":0,
                    "neon_stored_valid_source_stock_bars":552,
                }]
            },
            "tpex":{
                "official_current_listed_stocks_excluding_1589":898,
            },
        },
    }


def synthetic_current_2021():
    eligible=tuple(str(n) for n in range(1000,2093) if n!=1589)
    assert len(eligible)==1092
    days=tuple(ALL_2021_DAYS)
    assert len(days)==28 and days[0]==date(2021,11,23)
    assert days[-1]==date(2021,12,30)
    source={}
    for i,d in enumerate(days):
        source[d]=set(eligible[:900])
        if i<2:
            source[d].remove(eligible[0])
        if i==27:
            source[d].remove(eligible[1])
        if i<4:
            source[d].add(eligible[900])
    return baseline(),eligible,set(days),source,25_300,{"twse-2021-A.twseenc":"a"*64}


class Owner2021AesTWSE28DayCurrentCohortTests(unittest.TestCase):
    def test_five_year_2021_starts_nov23_not_an_entire_calendar_year(self):
        p,eligible,days,source,count,digests=synthetic_current_2021()
        r=evaluate_2021_aes_current_cohort(
            p,eligible=eligible,source_days=days,
            per_day_stocks=source,source_rows=count,
            aes_file_hashes=digests)
        self.assertEqual(r["scope"],SCOPE)
        self.assertEqual(r["five_year_baseline_window_start"],"2021-11-23")
        self.assertEqual(r["five_year_baseline_window_end_exclusive"],"2026-11-23")
        self.assertEqual(r["authenticated_2021_owner_aes_source_days"],28)
        self.assertEqual(r["2021_window_last_authenticated_source_day"],"2021-12-30")
        self.assertEqual(r["2021_aes_current_2026_twse_survivor_eligible_count"],1092)
        self.assertEqual(r["2021_2026_current_stocks_with_all_28_observed_source_days"],898)
        self.assertEqual(r["2021_2026_current_stocks_with_at_least_26_of_28_days"],899)
        self.assertEqual(r["2021_2026_current_stocks_with_no_2021_source_day"],191)
        self.assertEqual(r["2021_aes_current_2026_twse_stock_date_presence_pairs"],sum(
            len(v) for v in source.values()))
        histogram=r["2021_current_cohort_per_stock_source_days_histogram"]
        self.assertEqual(sum(histogram.values()),1092)
        self.assertEqual(histogram["28"],898)
        self.assertEqual(histogram["27"],1)
        self.assertEqual(histogram["26"],1)
        self.assertEqual(histogram["4"],1)
        self.assertEqual(histogram["0"],191)
        self.assertEqual(sum(v["authenticated_source_days"] for v in r[
            "monthly_authenticated_2021_current_cohort_source_density"].values()),28)
        self.assertEqual(r["neon_only_source_stock_date_count_in_2021_prior"],552)
        self.assertFalse(r[
            "2021_current_cohort_aes_neon_deduplicated_stock_day_union_verified"])
        self.assertTrue(r["historic_2021_unlisted_and_delisted_issuers_out_of_scope"])
        self.assertFalse(r["individual_ohlcv_and_total_returns_adjusted"])
        self.assertFalse(r["2022_2026_full_panel_model_validation_complete"])
        self.assertEqual(r["model_release"],"BLOCKED")
        self.assertEqual(r["production_neon_writes"],0)
        self.assertEqual(r["line_messages_sent"],0)
        self.assertNotIn("stock_id",str(r))
        self.assertNotIn("2330",str(r))

    def test_2021_owner_neon_baseline_cannot_be_pretended_as_aes_market_gap(self):
        p=baseline()
        self.assertTrue(verify_previous_baseline(p))
        for mode in ("no-aes-flag","different-neon-count","not-blocked",
                     "earlier-than-five-years","2021-other-window","wrong-exclusion"):
            old=deepcopy(p)
            if mode=="no-aes-flag":
                old["owner_aes_2021_2022_source_not_included"]=False
            elif mode=="different-neon-count":
                old["market"]["twse"]["yearly_neon_source_observations"][0][
                    "neon_stored_valid_source_stock_bars"]=700
            elif mode=="not-blocked":
                old["model_release"]="PASS"
            elif mode=="earlier-than-five-years":
                old["window_start_inclusive"]="2021-01-01"
            elif mode=="2021-other-window":
                old["window_end_exclusive"]="2026-11-24"
            else:
                old["market"]["twse"][
                    "official_current_listed_stocks_excluding_1589"]=1093
            with self.assertRaises(ValueError):
                verify_previous_baseline(old)

    def test_foreign_1589_new_stock_duplicate_date_and_changed_aes_digest_rejected(self):
        p,eligible,days,source,count,digests=synthetic_current_2021()
        base=dict(eligible=eligible,source_days=days,
                  per_day_stocks=source,source_rows=count,
                  aes_file_hashes=digests)
        for override in (
                {"eligible":(*eligible,"1589")},
                {"source_days":days-{date(2021,11,23)}},
                {"per_day_stocks":dict(source,**{
                    date(2021,11,23):set(source[date(2021,11,23)])|{"1589"}})},
                {"aes_file_hashes":{"file.twseenc":"bad"}},
                {"source_rows":MAX_R if (MAX_R:=45001) else 45001},
        ):
            with self.assertRaises(ValueError):
                evaluate_2021_aes_current_cohort(p,**(base|override))

    def test_no_fake_2021_source_stock_day_if_less_than_500_per_date(self):
        p,eligible,days,source,count,digests=synthetic_current_2021()
        source=dict(source)
        source[date(2021,11,23)]={"2330"}
        with self.assertRaises(ValueError):
            evaluate_2021_aes_current_cohort(
                p,eligible=eligible,source_days=days,
                per_day_stocks=source,source_rows=count,
                aes_file_hashes=digests)

    def test_2021_density_cli_synthetic_has_no_secret_requirements(self):
        env=os.environ.copy()
        for secret in ("DATABASE_URL","STOCK_ARCHIVE_KEY_HEX","PYTHONPATH"):
            env.pop(secret,None)
        root=Path(__file__).resolve().parents[1]
        proc=subprocess.run(
            [sys.executable,"-m",
             "scripts.twse_2021_28day_aes_current_cohort_density_readonly",
             "--help"],cwd=root,env=env,
            capture_output=True,text=True,timeout=20)
        self.assertEqual(proc.returncode,0,proc.stderr)
        for arg in ("--archive-2021","--key-vault",
                    "--five-year-neon-report","--out"):
            self.assertIn(arg,proc.stdout)


if __name__=="__main__":
    unittest.main()
