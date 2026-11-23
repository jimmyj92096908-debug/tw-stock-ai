"""Offline deterministic 116 currently-listed 2022 stock source absence evidence tests."""
from __future__ import annotations

from collections import Counter
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from scripts.twse_2022_116_internal_source_absence_triage import (
    SCOPE, triage_internal_source_absences,
)
from scripts.twse_2022_aes_neon_eligible_density_readonly import (
    classify_current_stock_source_absences,evaluate,
)
from tests.test_twse_2022_aes_neon_eligible_density_readonly import (
    inputs, synthetic_246,
)


def synthetic_owner_116():
    """Artificial 2022 all-source-day current survivors: 104 inside + 12 mixed."""
    days=synthetic_246()
    roster=tuple(str(i) for i in range(1000,2093) if i!=1589)
    assert len(roster)==1092 and len(days)==246
    actual={d:set(roster) for d in days}
    for sid in roster[:104]:
        actual[days[10]].remove(sid)
    for sid in roster[104:116]:
        actual[days[0]].remove(sid)
        actual[days[15]].remove(sid)
    per=Counter()
    bounds_first={}
    bounds_last={}
    for i,day in enumerate(days):
        for sid in actual[day]:
            per[sid]+=1
            bounds_first.setdefault(sid,i)
            bounds_last[sid]=i
    signature=classify_current_stock_source_absences(
        roster,per,bounds_first,bounds_last,source_day_count=len(days))
    assert signature["observation_signature_stock_count"][
        "internal_absent_days_only"]==104
    assert signature["observation_signature_stock_count"][
        "internal_and_outer_absent_days"]==12
    assert signature["nominal_absent_stock_source_date_pairs_inside_first_last"]==116
    return roster,days,actual,signature


class InternalSourceMissing2022Owner116OfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owner=synthetic_owner_116()

    def test_owner_116_real_source_date_streak_reconciled_not_assumed_missing_price(self):
        roster,days,actual,signature=self.owner
        r=triage_internal_source_absences(
            roster,days,actual,expected_signature=signature,
            enforce_owner_receipt=True)
        self.assertEqual(r["scope"],SCOPE)
        self.assertEqual(r["official_current_eligible_stocks"],1092)
        self.assertEqual(r["authenticated_aes_neon_observed_source_days"],246)
        c=r["source_observation_gap_count_signatures"]
        self.assertEqual(c["internal_absent_source_date_stock_count"],116)
        self.assertEqual(c["internal_only_stock_count"],104)
        self.assertEqual(c["internal_and_outer_stock_count"],12)
        self.assertEqual(c["internal_absent_stock_source_date_pairs"],116)
        self.assertEqual(c["disjoint_absence_run_count"],116)
        self.assertEqual(c["one_day_run_count"],116)
        self.assertEqual(c["two_to_five_day_run_count"],0)
        self.assertEqual(c["six_or_more_day_run_count"],0)
        rows=r["private_2022_current_stock_internal_absence_research_rows"]
        self.assertEqual(len(rows),116)
        self.assertEqual(
            set(row["stock_id"] for row in rows),set(roster[:116]))
        self.assertEqual(sum(
            item["unobserved_stock_source_date_pairs"] for item in
            r["monthly_internal_unobserved_eligible_stock_source_pairs"]),116)
        self.assertEqual(rows[0]["internal_unobserved_source_day_count"],1)
        self.assertTrue(r["stock_trading_halt_or_listing_eligibility_not_proven"])
        self.assertTrue(r["unobserved_source_day_is_not_approved_backfill_or_imputation"])
        self.assertTrue(r["observed_source_days_are_not_independent_historic_exchange_calendar"])
        self.assertFalse(r["historic_delisted_survivorship_unbiased"])
        self.assertEqual(r["model_release"],"BLOCKED")
        self.assertEqual(r["production_neon_writes"],0)
        self.assertEqual(r["line_messages_sent"],0)
        self.assertNotIn("close",str(r).lower())
        self.assertNotIn("volume",str(r).lower())

    def test_gap_streak_run_lengths_and_start_end_examples_are_observed_dates_only(self):
        days=synthetic_246()[:12]
        roster=("1001","1002","1003")
        data={d:set(roster) for d in days}
        for i in (1,2,3,6,8,9):
            data[days[i]].remove("1002")
        data[days[0]].remove("1003")
        for i in (4,5,6):
            data[days[i]].remove("1003")
        r=triage_internal_source_absences(roster,days,data)
        c=r["source_observation_gap_count_signatures"]
        self.assertEqual(c["internal_absent_source_date_stock_count"],2)
        self.assertEqual(c["internal_only_stock_count"],1)
        self.assertEqual(c["internal_and_outer_stock_count"],1)
        self.assertEqual(c["internal_absent_stock_source_date_pairs"],9)
        self.assertEqual(c["disjoint_absence_run_count"],4)
        self.assertEqual(c["one_day_run_count"],1)
        self.assertEqual(c["two_to_five_day_run_count"],3)
        rows={row["stock_id"]:row for row in
              r["private_2022_current_stock_internal_absence_research_rows"]}
        self.assertEqual(rows["1002"]["longest_internal_absence_run_source_days"],3)
        self.assertEqual(rows["1002"]["disjoint_internal_unobserved_runs"],3)
        samples=rows["1002"]["sample_two_longest_internal_absence_runs"]
        self.assertEqual(len(samples),2)
        self.assertEqual(samples[0]["first_unobserved_source_day"],days[1].isoformat())
        self.assertEqual(samples[0]["last_unobserved_source_day"],days[3].isoformat())
        self.assertEqual(rows["1003"]["observation_signature"],"INTERNAL_AND_OUTER")

    def test_prior_owner_signature_changes_or_116_exact_group_change_fails(self):
        roster,days,actual,signature=self.owner
        bad_sig=dict(signature)
        bad_sig["nominal_absent_stock_source_date_pairs_inside_first_last"]=117
        with self.assertRaisesRegex(ValueError,"drifted"):
            triage_internal_source_absences(
                roster,days,actual,expected_signature=bad_sig,
                enforce_owner_receipt=True)
        changed=dict(actual)
        changed[days[10]]=set(changed[days[10]])|{roster[0]}
        with self.assertRaises(ValueError):
            triage_internal_source_absences(
                roster,days,changed,expected_signature=signature,
                enforce_owner_receipt=True)

    def test_no_unlisted_1589_tampered_dates_or_stocks(self):
        roster,days,actual,_=self.owner
        changed=dict(actual); changed[days[10]]=set(changed[days[10]])|{"1589"}
        with self.assertRaises(ValueError):
            triage_internal_source_absences(roster,days,changed)
        with self.assertRaises(ValueError):
            triage_internal_source_absences((*roster,"1589"),days,actual)
        with self.assertRaises(ValueError):
            triage_internal_source_absences(roster,(*days,days[-1]),actual)
        changed=dict(actual);changed[date(2023,1,3)]=set()
        with self.assertRaises(ValueError):
            triage_internal_source_absences(roster,days,changed)

    def test_old_default_receipt_path_unchanged_116_flag_requires_evidence(self):
        p,b,o,roster,aes,bulk,neon,proof=inputs()
        baseline=evaluate(
            p,b,o,roster=roster,aes_by_day=aes,
            neon_bulk_days=bulk,neon_rows=neon,source_audit=proof)
        self.assertNotIn("owner_private_2022_116_internal_source_absence_triage",baseline)
        with self.assertRaisesRegex(ValueError,"changed"):
            evaluate(
                p,b,o,roster=roster,aes_by_day=aes,
                neon_bulk_days=bulk,neon_rows=neon,source_audit=proof,
                internal_gap_triage=True)

    def test_cli_and_no_credentials_source_prices_or_line(self):
        root=Path(__file__).resolve().parents[1]
        env=os.environ.copy()
        for secret in ("DATABASE_URL","STOCK_ARCHIVE_KEY_HEX","PYTHONPATH"):
            env.pop(secret,None)
        proc=subprocess.run(
            [sys.executable,"-m",
             "scripts.twse_2022_aes_neon_eligible_density_readonly",
             "--help"],cwd=root,env=env,capture_output=True,text=True,
            timeout=25)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertIn("--internal-gap-triage",proc.stdout)


if __name__=="__main__":
    unittest.main()
