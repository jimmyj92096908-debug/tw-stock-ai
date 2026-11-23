"""Synthetic-only owner 2022 AES+Neon stock-date full-cohort density contract."""
from __future__ import annotations

from datetime import date,timedelta
from collections import Counter
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock,patch

from scripts.twse_2022_aes_neon_eligible_density_readonly import (
    BULK, SECONDARY, SCOPE, STOCK_DATE_SQL, ELIGIBLE_SQL,
    BULK_DATES_SQL, capture_neon, evaluate, classify_current_stock_source_absences,
)
from scripts.twse_2022_aes_neon_five_year_overlay_offline import reconcile_offline
from tests.test_twse_2022_aes_neon_five_year_overlay_offline import old,fresh


def synthetic_246():
    # Artificial 2022 weekday calendar, NOT claimed to be official; reject
    # 14 interior weekdays to get the exact user-observed 246 endpoints.
    cur=date(2022,1,3)
    valid=[]
    while cur<=date(2022,12,30):
        if cur.weekday()<5:
            valid.append(cur)
        cur+=timedelta(days=1)
    assert len(valid)==260
    return tuple(valid[:80]+valid[94:])


def inputs():
    initial=old()
    initial["local_authenticated_source_rows"]=145000
    baseline=fresh()
    overlay=reconcile_offline(initial,baseline)
    roster=tuple(str(n) for n in range(1000,2093) if n!=1589)
    assert len(roster)==1092
    days=synthetic_246()
    aes_days=days[:162]
    bulk=days[162:]
    aes={d:set(roster[:800]) for d in aes_days}
    neon=[]
    # 84 dense source days x 989 = 83,076; 162 sparse date rows plus
    # 56 second sparse shares = 218; total 83,294 same as owner Neon report.
    for day in bulk:
        neon.extend((day,sid,BULK) for sid in roster[:989])
    for index,day in enumerate(aes_days):
        neon.append((day,roster[0],SECONDARY))
        if index<56:
            neon.append((day,roster[1],SECONDARY))
    assert len(neon)==83294
    source_audit={
        "authenticated_source_rows":145000,
        "authentic_distinct_2022_source_sessions":162,
        "neon_connections":0,
        "neon_rows_written":0,
        "live_model_release_decision":"BLOCKED",
    }
    return initial,baseline,overlay,roster,aes,list(bulk),neon,source_audit


def run(args):
    p,b,o,roster,aes,bulk,neon,proof=args
    return evaluate(p,b,o,roster=roster,aes_by_day=aes,
                    neon_bulk_days=bulk,neon_rows=neon,source_audit=proof)


class AESNeonCurrentListed2022DensityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference=inputs()

    def test_full_current_market_year_density_not_five_year_or_pit(self):
        r=run(self.reference)
        self.assertEqual(r["scope"],SCOPE)
        self.assertEqual(r["official_current_listed_eligible_twse_issuers"],1092)
        self.assertEqual(r["aes_prior_2022_source_calendar_dates"],162)
        self.assertEqual(r["aes_dates_with_at_least_500_current_eligible_stock_bars"],162)
        self.assertEqual(r["neon_rechecked_stock_date_source_rows"],83294)
        self.assertEqual(r["neon_original_bulk_source_calendar_dates"],84)
        self.assertTrue(r["neon_bulk_date_set_matches_500_stock_density_date_set"])
        self.assertEqual(r["neon_2022_stock_dates_with_any_current_eligible_source_bars"],246)
        self.assertEqual(r["aes_neon_merged_days_with_at_least_500_current_eligible_stock_bars"],246)
        self.assertEqual(r["aes_neon_current_listed_stocks_with_all_246_source_dates"],800)
        self.assertEqual(r["aes_neon_current_listed_stocks_with_at_least_240_of_246_source_dates"],800)
        signature=r["current_listed_source_date_observation_absence_signatures"]
        self.assertEqual(signature["eligible_stocks_not_observed_on_all_source_days"],292)
        self.assertEqual(signature["observation_signature_stock_count"]["all_observed_source_days"],800)
        self.assertEqual(signature["observation_signature_stock_count"]["absence_only_before_first_observed_day"],189)
        self.assertEqual(signature["observation_signature_stock_count"]["no_observed_source_day"],103)
        self.assertEqual(signature["observation_signature_stock_count"]["internal_absent_days_only"],0)
        self.assertTrue(signature["no_absence_is_a_certified_data_fetch_gap"])
        self.assertEqual(sum(x["source_dates"] for x in
                             r["aes_neon_2022_monthly_source_date_density"]),246)
        self.assertFalse(r["full_market_all_stock_daily_bar_completeness_certified"])
        self.assertFalse(r["historical_delisted_survivorship_bias_eliminated"])
        self.assertFalse(r["five_year_all_stock_source_depth_certified"])
        self.assertFalse(r["historical_adjusted_total_returns_approved"])
        self.assertEqual(r["production_neon_writes"],0)
        self.assertEqual(r["line_messages_sent"],0)
        self.assertEqual(r["model_release"],"BLOCKED")
        self.assertNotIn("raw_close",str(r))

    def test_all_seven_absence_signatures_are_nonoverlapping_and_accounted(self):
        roster=("A","B","C","D","E","F","G")
        counts=Counter({"A":10,"C":8,"D":7,"E":5,"F":9,"G":6})
        first={"A":0,"C":2,"D":0,"E":2,"F":0,"G":2}
        last={"A":9,"C":9,"D":6,"E":6,"F":9,"G":8}
        r=classify_current_stock_source_absences(
            roster,counts,first,last,source_day_count=10)
        expected={
            "all_observed_source_days":1,
            "no_observed_source_day":1,
            "absence_only_before_first_observed_day":1,
            "absence_only_after_last_observed_day":1,
            "absence_at_both_outer_boundaries_only":1,
            "internal_absent_days_only":1,
            "internal_and_outer_absent_days":1,
        }
        self.assertEqual(r["observation_signature_stock_count"],expected)
        self.assertEqual(r["eligible_stocks_not_observed_on_all_source_days"],6)
        self.assertEqual(r["nominal_absent_stock_source_date_pairs_before_first"],6)
        self.assertEqual(r["nominal_absent_stock_source_date_pairs_after_last"],7)
        self.assertEqual(r["nominal_absent_stock_source_date_pairs_inside_first_last"],2)
        self.assertEqual(r["nominal_absent_stock_source_date_pairs_no_2022_record"],10)
        self.assertEqual(r["nominal_absent_stock_source_date_pairs_total"],25)
        self.assertTrue(r["boundary_absence_is_not_verified_as_pre_ipo_or_delisting"])
        self.assertTrue(r["internal_absence_may_be_authentic_halt_or_unresolved_source_gap"])

    def test_absence_classifier_rejects_duplicate_or_impossible_observation(self):
        roster=("A","B")
        for bad_roster,counts,first,last in (
            (("A","A"),Counter({"A":1}),{"A":0},{"A":0}),
            (roster,Counter({"A":4}),{"A":0},{"A":1}),
            (roster,Counter({"A":1}),{"A":3},{"A":1}),
            (roster,Counter({"A":1}),{},{"A":0}),
            (roster,Counter({"A":1,"X":1}),{"A":0,"X":0},{"A":0,"X":0}),
        ):
            with self.assertRaises(ValueError):
                classify_current_stock_source_absences(
                    bad_roster,counts,first,last,source_day_count=10)

    def test_same_dense_counts_can_hide_wrong_date_set(self):
        p,b,o,roster,aes,bulk,neon,proof=self.reference
        moved_from=bulk[0]
        moved_to=synthetic_246()[0]
        moved_ids=set(roster[2:502])
        self.assertEqual(len(moved_ids),500)
        changed=[]
        moved=0
        for d,s,source in neon:
            if d==moved_from and s in moved_ids:
                changed.append((moved_to,s,SECONDARY))
                moved+=1
            else:
                changed.append((d,s,source))
        self.assertEqual(moved,500)
        # Same 84 dense days, same 83,294 rows; but one dense date shifted
        # outside actual 84 official-bulk days. Must not mark exact parity.
        r=run((p,b,o,roster,aes,bulk,changed,proof))
        self.assertEqual(r["neon_2022_dates_with_at_least_500_current_eligible_stock_bars"],84)
        self.assertFalse(r["neon_bulk_date_set_matches_500_stock_density_date_set"])
        self.assertEqual(r["neon_bulk_days_below_500"],[moved_from.isoformat()])
        self.assertEqual(r["neon_high_density_days_outside_original_bulk"],[moved_to.isoformat()])
        self.assertFalse(r["full_market_all_stock_daily_bar_completeness_certified"])

    def test_stale_previous_or_tampered_five_year_report_rejected(self):
        p,b,o,roster,aes,bulk,neon,proof=self.reference
        bad=dict(o,model_release="APPROVED")
        with self.assertRaises(ValueError):
            run((p,b,bad,roster,aes,bulk,neon,proof))
        bad=dict(p,neon_write_operations=1)
        with self.assertRaises(ValueError):
            run((bad,b,o,roster,aes,bulk,neon,proof))

    def test_unlisted_stock_or_1589_cannot_be_counted(self):
        p,b,o,roster,aes,bulk,neon,proof=self.reference
        bad=list(roster)
        bad[0]="1589"
        with self.assertRaises(ValueError):
            run((p,b,o,bad,aes,bulk,neon,proof))
        bad=list(neon)
        bad[0]=(bad[0][0],"1589",BULK)
        with self.assertRaises(ValueError):
            run((p,b,o,roster,aes,bulk,bad,proof))

    def test_neon_source_2022_mismatches_fail_closed(self):
        p,b,o,roster,aes,bulk,neon,proof=self.reference
        bad=list(neon)
        bad.append(neon[-1])
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            run((p,b,o,roster,aes,bulk,bad,proof))
        bad=list(neon)
        bad[0]=(date(2023,1,2),bad[0][1],BULK)
        with self.assertRaises(ValueError):
            run((p,b,o,roster,aes,bulk,bad,proof))
        bad=list(neon)
        bad[0]=(bad[0][0],bad[0][1],"OTHER_UNKNOWN")
        with self.assertRaises(ValueError):
            run((p,b,o,roster,aes,bulk,bad,proof))

    def test_2022_aes_below_500_no_full_source_claim(self):
        p,b,o,roster,aes,bulk,neon,proof=self.reference
        subset=dict(aes)
        special=min(subset)
        subset[special]=set(roster[:250])
        r=run((p,b,o,roster,subset,bulk,neon,proof))
        self.assertEqual(r["aes_dates_below_500_current_eligible_stock_bars"],1)
        self.assertEqual(r["aes_neon_merged_days_with_at_least_500_current_eligible_stock_bars"],245)
        self.assertFalse(r["full_market_all_stock_daily_bar_completeness_certified"])

    def test_database_source_queries_filter_current_listing_no_writes(self):
        self.assertIn("official_current_listed",ELIGIBLE_SQL)
        self.assertIn("stock_id <> '1589'",ELIGIBLE_SQL)
        self.assertIn("model_stock_exclusions",ELIGIBLE_SQL)
        self.assertIn("official_current_listed",STOCK_DATE_SQL)
        self.assertIn("p.close > 0",STOCK_DATE_SQL)
        self.assertIn("p.volume >= 0",STOCK_DATE_SQL)
        self.assertIn("2022-01-01",STOCK_DATE_SQL)
        self.assertIn("2023-01-01",STOCK_DATE_SQL)
        self.assertIn("source='TWSE_MI_INDEX_ALLBUT0999'",BULK_DATES_SQL)
        for sql in (ELIGIBLE_SQL,STOCK_DATE_SQL,BULK_DATES_SQL):
            self.assertNotIn("UPDATE ",sql.upper())
            self.assertNotIn("INSERT ",sql.upper())
            self.assertNotIn("DELETE ",sql.upper())

    def test_database_reads_in_one_explicit_readonly_transaction(self):
        conn=Mock();conn.__enter__=Mock(return_value=conn);conn.__exit__=Mock(return_value=False)
        cursor=Mock();cursor.__enter__=Mock(return_value=cursor);cursor.__exit__=Mock(return_value=False)
        conn.cursor.return_value=cursor
        def result(sql):
            if sql==ELIGIBLE_SQL:
                cursor.fetchall.return_value=[("2327",)]
            elif sql==BULK_DATES_SQL:
                cursor.fetchall.return_value=[(date(2022,10,31),)]
            elif sql==STOCK_DATE_SQL:
                cursor.fetchmany.side_effect=[[(
                    date(2022,10,31),"2327",BULK)],[]]
            return cursor
        cursor.execute.side_effect=result
        with patch("psycopg.connect",return_value=conn):
            roster,bulk,stock_dates=capture_neon("postgresql://fake/db")
        self.assertEqual(roster,["2327"])
        self.assertEqual(bulk,[date(2022,10,31)])
        self.assertEqual(len(stock_dates),1)
        conn.rollback.assert_called_once()
        statements=[c.args[0] for c in cursor.execute.call_args_list]
        self.assertTrue(any("READ ONLY" in s for s in statements))
        self.assertTrue(any("statement_timeout" in s for s in statements))

    def test_cli_help_without_private_data_or_credentials(self):
        root=Path(__file__).resolve().parents[1]
        env=os.environ.copy()
        for k in ("DATABASE_URL","STOCK_ARCHIVE_KEY_HEX","PYTHONPATH"):
            env.pop(k,None)
        proc=subprocess.run(
            [sys.executable,"-m","scripts.twse_2022_aes_neon_eligible_density_readonly",
             "--help"],cwd=root,env=env,
            capture_output=True,text=True,timeout=25)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertIn("--archive-2022",proc.stdout)
        self.assertIn("--prior-overlay-report",proc.stdout)


if __name__=="__main__":
    unittest.main()
