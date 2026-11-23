"""Synthetic exact 2021 28-day AES/Neon stock/date union, no real secrets."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import os
from pathlib import Path
import subprocess
import sys
import unittest

from scripts.twse_2021_28day_aes_current_cohort_density_readonly import (
    EXPECTED_DAYS, evaluate_2021_aes_current_cohort,
)
from scripts.twse_2021_28day_aes_neon_stockdate_union_readonly import (
    SCOPE, evaluate_2021_union, _proof_241,
)
from tests.test_twse_2021_28day_aes_current_cohort_density_readonly import (
    baseline,
)


def frozen_owner_2021():
    prior_neon=baseline()
    roster=tuple(str(i) for i in range(1000,2093) if i!=1589)
    assert len(roster)==1092
    full=roster[:900]
    almost=roster[900:916]
    middle=roster[916:938]
    single=roster[938]
    empty=roster[939:]
    assert len(almost)==16 and len(middle)==22 and len(empty)==153
    dates=tuple(EXPECTED_DAYS)
    assert len(dates)==28
    aes={}
    for i,d in enumerate(dates):
        aes[d]=set(full)
        if i<26:
            aes[d].update(almost)
        if i<22:
            aes[d].update(middle)
        if i<20:
            aes[d].add(single)
    assert sum(map(len,aes.values()))==26120
    prior_aes=evaluate_2021_aes_current_cohort(
        prior_neon,eligible=roster,source_days=set(dates),
        per_day_stocks=aes,source_rows=26400,
        aes_file_hashes={"2021-private-fixture.twseenc":"b"*64})
    assert prior_aes["2021_2026_current_stocks_with_all_28_observed_source_days"]==900
    assert prior_aes["2021_2026_current_stocks_with_at_least_26_of_28_days"]==916
    assert prior_aes["2021_2026_current_stocks_with_no_2021_source_day"]==153
    neon=[]
    for i,d in enumerate(dates):
        count=20 if i<20 else 19
        selected=list(full[:count])
        if i<2:
            selected[0]=empty[0] # 2 extra Neon-only source stock/date keys
        for sid in selected:
            neon.append((d,sid,"TWSE_STOCK_DAY"))
    assert len(neon)==552
    return prior_neon,prior_aes,roster,aes,neon


class Owner2021OriginalAESNeonStockDateUnionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=frozen_owner_2021()

    def calculate(self,**overrides):
        old5y,oldAES,roster,aes,neon=self.fixture
        p=dict(prior_aes=oldAES,prior_neon=old5y,
               recomputed_aes=oldAES,roster=roster,aes_by_day=aes,
               neon_rows=neon)
        p.update(overrides)
        return evaluate_2021_union(**p)

    def test_real_stock_date_dedup_26120_plus_552_minus_550(self):
        r=self.calculate()
        self.assertEqual(r["scope"],SCOPE)
        self.assertEqual(r["authenticated_owner_2021_source_dates"],28)
        self.assertEqual(r["prior_2021_aes_source_stock_date_pairs"],26120)
        self.assertEqual(r["prior_2021_neon_source_stock_date_pairs"],552)
        self.assertEqual(r["aes_neon_overlapping_source_stock_date_pairs"],550)
        self.assertEqual(r["aes_exclusive_source_stock_date_pairs"],25570)
        self.assertEqual(r["neon_exclusive_source_stock_date_pairs"],2)
        self.assertEqual(r["actual_deduplicated_aes_neon_stock_date_pairs"],26122)
        self.assertEqual(r["current_stocks_with_all_28_original_source_dates"],900)
        self.assertEqual(r["current_stocks_with_at_least_26_of_28_source_dates"],916)
        self.assertEqual(r["current_stocks_with_no_source_day_in_2021"],152)
        self.assertEqual(sum(r["current_stock_source_day_count_histogram"].values()),1092)
        self.assertEqual(sum(x["deduplicated_source_stock_date_pairs"]
                             for x in r["source_monthly_deduplicated_density"].values()),
                         26122)
        self.assertEqual(sum(x["duplicate_aes_neon_stock_date_pairs"]
                             for x in r["source_monthly_deduplicated_density"].values()),
                         550)
        self.assertTrue(r["unobserved_issuer_source_day_not_proven_missing_price"])
        self.assertTrue(r["current_issuer_2026_roster_is_not_historical_2021_pit_roster"])
        self.assertFalse(r["official_historic_ipo_halts_board_trading_eligibility_verified"])
        self.assertFalse(r["full_corporate_action_total_return_adjusted"])
        self.assertEqual(r["model_release"],"BLOCKED")
        self.assertEqual(r["production_neon_writes"],0)
        self.assertEqual(r["line_messages_sent"],0)
        self.assertNotIn("2330",str(r))
        self.assertNotIn("stock_id",str(r))
        self.assertNotIn("ohlcv",str(r).lower())

    def test_old_241_receipt_tamper_and_wrong_source_fails_closed(self):
        old5y,oldAES,roster,aes,neon=self.fixture
        self.assertIsNone(_proof_241(oldAES))
        changed=deepcopy(oldAES)
        changed["2021_aes_current_2026_twse_stock_date_presence_pairs"]=26119
        with self.assertRaises(ValueError):
            self.calculate(prior_aes=changed)
        changed=deepcopy(oldAES)
        changed["monthly_authenticated_2021_current_cohort_source_density"][
            "2021-11"]["current_stock_day_presence_pairs"]+=1
        with self.assertRaises(ValueError):
            self.calculate(recomputed_aes=changed)
        changed=deepcopy(old5y)
        changed["market"]["twse"]["yearly_neon_source_observations"][0][
            "neon_stored_valid_source_stock_bars"]=553
        with self.assertRaises(ValueError):
            self.calculate(prior_neon=changed)

    def test_neon_duplicate_1589_bad_dates_and_source_rows_rejected(self):
        _,_,roster,aes,neon=self.fixture
        corrupted=[
            neon[:-1],
            neon[:-1]+[neon[0]],
            neon[:-1]+[(date(2021,11,22),roster[0],"TWSE_STOCK_DAY")],
            neon[:-1]+[(neon[-1][0],"1589","TWSE_STOCK_DAY")],
            neon[:-1]+[(neon[-1][0],roster[0],"FAKE_SOURCE")],
            neon[:-1]+[(neon[-1][0],"9999","TWSE_STOCK_DAY")],
        ]
        for rows in corrupted:
            with self.subTest(corruption=str(rows[-1])):
                with self.assertRaises(ValueError):
                    self.calculate(neon_rows=rows)

    def test_local_aes_out_of_scope_issuer_source_day_mismatch_rejected(self):
        _,_,roster,aes,neon=self.fixture
        bad={d:set(s) for d,s in aes.items()}
        bad[EXPECTED_DAYS[0]].add("1589")
        with self.assertRaises(ValueError):
            self.calculate(aes_by_day=bad)
        bad={d:set(s) for d,s in aes.items()}
        bad[EXPECTED_DAYS[0]].remove(roster[0])
        with self.assertRaises(ValueError):
            self.calculate(aes_by_day=bad)
        with self.assertRaises(ValueError):
            self.calculate(roster=(*roster,"1589"))

    def test_neon_even_if_all_552_overlapped_union_cannot_be_sum(self):
        p,a,roster,keys,old=self.fixture
        neon=[]
        for i,d in enumerate(EXPECTED_DAYS):
            count=20 if i<20 else 19
            neon.extend((d,sid,"TWSE_STOCK_DAY")
                        for sid in roster[:count])
        r=self.calculate(neon_rows=neon)
        self.assertEqual(r["aes_neon_overlapping_source_stock_date_pairs"],552)
        self.assertEqual(r["neon_exclusive_source_stock_date_pairs"],0)
        self.assertEqual(r["actual_deduplicated_aes_neon_stock_date_pairs"],26120)
        self.assertEqual(r["current_stocks_with_no_source_day_in_2021"],153)

    def test_help_uses_private_paths_only_no_credentials_required_in_ci(self):
        env=os.environ.copy()
        for key in ("DATABASE_URL","STOCK_ARCHIVE_KEY_HEX","PYTHONPATH"):
            env.pop(key,None)
        result=subprocess.run(
            [sys.executable,"-m",
             "scripts.twse_2021_28day_aes_neon_stockdate_union_readonly",
             "--help"],cwd=Path(__file__).resolve().parents[1],
            capture_output=True,text=True,timeout=20,env=env)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("--archive-2021",result.stdout)
        self.assertIn("--prior-241-aes-report",result.stdout)
        self.assertIn("--prior-five-year-neon-report",result.stdout)
        self.assertIn("--out",result.stdout)


if __name__=="__main__":
    unittest.main()
