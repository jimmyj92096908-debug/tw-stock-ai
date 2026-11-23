"""Synthetic 2021 owner AES + Neon stock/day union, no secret or production DB."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import os
from pathlib import Path
import subprocess
import sys
import unittest

from scripts.twse_2021_28day_aes_current_cohort_density_readonly import (
    EXPECTED_DAYS,evaluate_2021_aes_current_cohort,
)
from scripts.twse_2021_28day_aes_neon_stock_date_union_readonly import (
    SCOPE, STOCK_DATE_SQL, reconcile_union,validate_immutable_241,
)
from tests.test_twse_2021_28day_aes_current_cohort_density_readonly import (
    baseline,
)


def source_fixture():
    prior_five=baseline()
    roster=tuple(str(i) for i in range(1000,2093) if i!=1589)
    days=tuple(EXPECTED_DAYS)
    assert len(roster)==1092 and len(days)==28
    aes={}
    for i,day in enumerate(days):
        names=set(roster[:900])
        if i<26:
            names.update(roster[900:916])
        if i<22:
            names.update(roster[916:937])
        if i<21:
            names.update(roster[937:939])
        aes[day]=names
    assert sum(len(v) for v in aes.values())==26120
    prior_aes=evaluate_2021_aes_current_cohort(
        prior_five,eligible=roster,source_days=set(days),
        per_day_stocks=aes,source_rows=27000,
        aes_file_hashes={"twse-2021-archive.twseenc":"b"*64})
    assert prior_aes[
        "2021_2026_current_stocks_with_all_28_observed_source_days"]==900
    assert prior_aes[
        "2021_2026_current_stocks_with_at_least_26_of_28_days"]==916
    assert prior_aes[
        "2021_2026_current_stocks_with_no_2021_source_day"]==153

    neon=[]
    for i,d in enumerate(days):
        existing=roster[:15] if i==0 else roster[:(20 if i<20 else 19)]
        extra=roster[939:944] if i==0 else ()
        for sid in (*existing,*extra):
            neon.append((d,sid,
                         "TWSE_MI_INDEX_ALLBUT0999" if i==0
                         else "TWSE_STOCK_DAY"))
    assert len(neon)==552
    return prior_five,prior_aes,roster,aes,neon


class Owner2021AesNeonUnionOfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=source_fixture()

    def test_exact_five_year_2021_aes_neon_dedup_552_including_5_new_stock_days(self):
        base,old,roster,aes,neon=self.data
        report=reconcile_union(
            base,old,roster=roster,aes_by_day=aes,
            neon_rows=neon,reverified_241=old)
        self.assertEqual(report["scope"],SCOPE)
        self.assertEqual(report["aes_current_stock_source_date_pairs"],26120)
        self.assertEqual(report["neon_current_stock_source_date_pairs"],552)
        self.assertEqual(report["duplicated_aes_neon_current_stock_date_pairs"],547)
        self.assertEqual(report["new_neon_current_stock_date_pairs_outside_aes"],5)
        self.assertEqual(report["unique_aes_plus_neon_2021_stock_date_pairs"],26125)
        self.assertEqual(report["aes_plus_neon_current_stocks_with_all_28_source_days"],900)
        self.assertEqual(report["aes_plus_neon_current_stocks_with_at_least_26_source_days"],916)
        self.assertEqual(report["aes_plus_neon_current_stocks_with_zero_2021_source_days"],148)
        self.assertEqual(report["official_current_twse_survivor_eligible_count"],1092)
        self.assertEqual(report["valid_neon_2021_source_days"],28)
        self.assertEqual(report["neon_2021_valid_source_tag_counts"],{
            "TWSE_MI_INDEX_ALLBUT0999":20,"TWSE_STOCK_DAY":532})
        self.assertTrue(report["previous_pr241_receipt_fully_reauthenticated"])
        self.assertTrue(report[
            "2021_current_cohort_aes_neon_deduplicated_stock_day_union_verified"])
        self.assertTrue(report["2021_zero_source_stocks_not_confirmed_missing_data"])
        self.assertTrue(report["source_key_union_not_price_or_volume_economic_parity"])
        self.assertTrue(report["full_five_year_and_corporate_action_total_return_not_verified"])
        self.assertTrue(report["model_walkforward_holdout_not_verified"])
        self.assertEqual(report["production_neon_writes"],0)
        self.assertEqual(report["line_messages_sent"],0)
        self.assertEqual(report["model_release"],"BLOCKED")
        self.assertFalse(report["paid_service_used"])
        self.assertFalse(report["owner_aes_raw_prices_not_stored_in_neon_by_this_process"] is False)
        self.assertNotIn("2330",str(report))
        self.assertNotIn("stock_id",str(report))
        months=report["monthly_aes_neon_source_stock_date_union_density"]
        self.assertEqual(set(months),{"2021-11","2021-12"})
        self.assertEqual(months["2021-11"]["observed_official_source_days"],6)
        self.assertEqual(months["2021-12"]["observed_official_source_days"],22)
        self.assertEqual(sum(v["union_unique_current_stock_date_pairs"]
                             for v in months.values()),26125)

    def test_old_241_receipt_must_match_replayed_aes_exactly(self):
        base,old,roster,aes,neon=self.data
        self.assertTrue(validate_immutable_241(old))
        for key,val in (
            ("2021_aes_current_2026_twse_stock_date_presence_pairs",26119),
            ("2021_2026_current_stocks_with_all_28_observed_source_days",899),
            ("2021_2026_current_stocks_with_no_2021_source_day",152),
            ("model_release","APPROVED"),
            ("production_neon_writes",1),
        ):
            changed=dict(old,**{key:val})
            with self.assertRaises(ValueError):
                reconcile_union(base,changed,roster=roster,
                                aes_by_day=aes,neon_rows=neon,
                                reverified_241=old)
        changed=deepcopy(old)
        changed["monthly_authenticated_2021_current_cohort_source_density"][
            "2021-12"]["current_stock_day_presence_pairs"]=20000
        with self.assertRaisesRegex(ValueError,"changed"):
            reconcile_union(base,old,roster=roster,aes_by_day=aes,
                            neon_rows=neon,reverified_241=changed)

    def test_duplicate_1589_unlisted_wrong_source_date_and_neon_count_rejected(self):
        base,old,roster,aes,neon=self.data
        altered=list(neon);altered[1]=altered[0]
        for new_roster,new_aes,new_neon in (
            (roster,aes,altered),
            ((*roster,"1589"),aes,neon),
            (roster,aes,[*neon[:-1],(date(2021,1,4),
                                        neon[-1][1],neon[-1][2])]),
            (roster,aes,[*neon[:-1],(neon[-1][0],
                                        "1589",neon[-1][2])]),
            (roster,aes,[*neon[:-1],(neon[-1][0],
                                        neon[-1][1],"UNVERIFIED_VENDOR")]),
            (roster,aes,neon[:-1]),
        ):
            with self.assertRaises(ValueError):
                reconcile_union(base,old,roster=new_roster,
                                aes_by_day=new_aes,neon_rows=new_neon,
                                reverified_241=old)

    def test_no_synthetic_imputation_current_survivors_not_historical_pit(self):
        base,old,roster,aes,neon=self.data
        bad=dict(aes)
        bad[EXPECTED_DAYS[0]]=set(bad[EXPECTED_DAYS[0]])|{"1589"}
        with self.assertRaises(ValueError):
            reconcile_union(base,old,roster=roster,aes_by_day=bad,
                            neon_rows=neon,reverified_241=old)
        ok=reconcile_union(base,old,roster=roster,aes_by_day=aes,
                           neon_rows=neon,reverified_241=old)
        self.assertEqual(ok["historic_asof_listed_universe_and_ipo_eligibility_not_proven"],True)
        self.assertEqual(ok["no_official_halt_auto_classification_or_price_imputation"],True)
        self.assertEqual(ok["unique_aes_plus_neon_2021_stock_date_pairs"],
                         ok["aes_current_stock_source_date_pairs"]+
                         ok["neon_current_stock_source_date_pairs"]-
                         ok["duplicated_aes_neon_current_stock_date_pairs"])

    def test_readonly_sql_current_official_issuer_and_cli_without_credentials(self):
        self.assertIn("official_current_listed",STOCK_DATE_SQL)
        self.assertIn("model_stock_exclusions",STOCK_DATE_SQL)
        self.assertIn("p.close > 0",STOCK_DATE_SQL)
        self.assertIn("p.volume >= 0",STOCK_DATE_SQL)
        self.assertIn("'2021-11-23'",STOCK_DATE_SQL)
        self.assertIn("'2022-01-01'",STOCK_DATE_SQL)
        self.assertNotIn("UPDATE public.daily_prices",STOCK_DATE_SQL)
        self.assertNotIn("INSERT INTO public.daily_prices",STOCK_DATE_SQL)
        env=os.environ.copy()
        for secret in ("DATABASE_URL","STOCK_ARCHIVE_KEY_HEX","PYTHONPATH"):
            env.pop(secret,None)
        p=subprocess.run(
            [sys.executable,"-m",
             "scripts.twse_2021_28day_aes_neon_stock_date_union_readonly",
             "--help"],
            cwd=Path(__file__).resolve().parents[1],
            env=env,capture_output=True,text=True,timeout=25)
        self.assertEqual(p.returncode,0,p.stderr)
        for f in ("--archive-2021","--key-vault",
                  "--five-year-neon-report",
                  "--prior-241-aes-report","--out"):
            self.assertIn(f,p.stdout)


if __name__=="__main__":
    unittest.main()
