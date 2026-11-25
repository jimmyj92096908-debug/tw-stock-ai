"""Synthetic receipts only. Never claim owner private receipts were opened."""
import copy
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

from scripts import twse_private_history_receipt_overlay_offline as overlay


def fixtures():
    common = {"schema_version":1,"production_neon_writes":0,
              "line_messages_sent":0,"model_release":"BLOCKED"}
    a = dict(common, scope=overlay.S21,
        five_year_baseline_window_start="2021-11-23",
        five_year_baseline_window_end_exclusive="2026-11-23",
        current_issuer_2026_roster_is_not_historical_2021_pit_roster=True,
        official_current_survivor_tickers_excluding_1589=1092,
        authenticated_owner_2021_source_dates=28,
        prior_2021_aes_source_stock_date_pairs=26120,
        prior_2021_neon_source_stock_date_pairs=552,
        aes_neon_overlapping_source_stock_date_pairs=552,
        aes_exclusive_source_stock_date_pairs=25568,
        neon_exclusive_source_stock_date_pairs=0,
        actual_deduplicated_aes_neon_stock_date_pairs=26120,
        current_stock_source_day_count_histogram={"28":900,"26":16,"22":22,"20":1,"0":153})
    b = dict(common, scope=overlay.S22,year=2022,
        official_current_listed_eligible_twse_issuers=1092,
        aes_prior_2022_source_calendar_dates=162,
        neon_original_bulk_source_calendar_dates=84,
        aes_source_days_overlap_neon_bulk_source_days=0,
        aes_plus_neon_unique_observed_source_dates=246,
        neon_rechecked_stock_date_source_rows=83294,
        aes_neon_current_listed_stocks_with_all_246_source_dates=825,
        aes_neon_current_listed_stocks_with_at_least_240_of_246_source_dates=890,
        full_market_all_stock_daily_bar_completeness_certified=False,
        source_day_presence_and_240_count_not_adjusted_total_return_or_historical_pit=True)
    b["current_listed_source_date_observation_absence_signatures"] = {
        "observation_signature_stock_count": dict(zip(overlay.GROUPS,[825,129,20,2,0,104,12])),
        "eligible_stocks_not_observed_on_all_source_days":267,
        "currently_eligible_stocks_observed_240_to_245_source_days":65,
        "currently_eligible_stocks_observed_fewer_than_240_source_days":202,
        "nominal_absent_stock_source_date_pairs_before_first":3000,
        "nominal_absent_stock_source_date_pairs_after_last":1000,
        "nominal_absent_stock_source_date_pairs_inside_first_last":2898,
        "nominal_absent_stock_source_date_pairs_no_2022_record":31734,
        "nominal_absent_stock_source_date_pairs_total":38632,
    }
    def market(pop, rows):
        return {"official_current_listed_stocks_excluding_1589":pop,
                "yearly_neon_source_observations":[
                    {"year":y,"days_with_any_neon_eligible_source_bars":d,
                     "days_with_at_least_500_eligible_source_bars":k,
                     "neon_stored_valid_source_stock_bars":v}
                    for y,d,k,v in rows]}
    c = dict(common,scope=overlay.S5,window_start_inclusive="2021-11-23",
        window_end_exclusive="2026-11-23",
        current_listed_issuers_only_not_historical_pit_membership=True,
        excludes_owner_private_aes_and_non_neon_source_history=True,
        five_year_history_completed=False,
        market={
            "twse":market(1092,[(2021,28,0,552),(2022,246,84,83294),
                (2023,239,239,231655),(2024,242,242,243484),
                (2025,243,243,252421),(2026,213,213,229215)]),
            "tpex":market(898,[(2021,28,28,20585),(2022,246,246,183123),
                (2023,239,239,184133),(2024,242,242,193140),
                (2025,243,243,200369),(2026,213,213,184147)])})
    return a,b,c


class ReceiptOverlayTests(unittest.TestCase):
    def test_independent_manual_arithmetic_and_blockers(self):
        x = overlay.reconcile(*fixtures())
        self.assertEqual(x["twse_2022_union_observed_keys_from_absence_conservation"],230000)
        self.assertEqual(x["conditional_increment_over_neon_only_baseline"],172274)
        self.assertEqual(x["twse_2021_2022_observed_keys_sum"],256120)
        self.assertFalse(x["same_roster_identifiers_and_snapshot_vintage_verified"])
        self.assertFalse(x["five_year_per_stock_depth_recomputed"])
        self.assertFalse(x["five_year_history_complete"])
        self.assertEqual(x["model_release"],"BLOCKED")

    def test_both_existing_producers_interoperate_without_inventing_source_counts(self):
        from scripts.twse_2021_28day_aes_neon_stockdate_union_readonly import evaluate_2021_union
        from scripts.twse_2021_28day_aes_neon_stock_date_union_readonly import reconcile_union
        from tests.test_twse_2021_28day_aes_neon_stockdate_union_readonly import frozen_owner_2021
        from tests.test_twse_2021_28day_aes_neon_stock_date_union_readonly import source_fixture
        # Existing producers, synthetic source keys. Force every 552 Neon key
        # to be an existing AES key to reproduce the fixed owner receipt shape.
        base, prior, roster, aes, _ = frozen_owner_2021()
        neon = [(d,sid,"TWSE_STOCK_DAY") for i,d in enumerate(sorted(aes))
                for sid in roster[:(20 if i<20 else 19)]]
        original = evaluate_2021_union(prior_aes=prior,prior_neon=base,
            recomputed_aes=prior,roster=roster,aes_by_day=aes,neon_rows=neon)
        base, prior, roster, aes, _ = source_fixture()
        alternate = reconcile_union(base,prior,roster=roster,aes_by_day=aes,
                                    neon_rows=neon,reverified_241=prior)
        _,b,c=fixtures()
        result=overlay.reconcile(original,b,c)
        self.assertEqual(result,overlay.reconcile(alternate,b,c))
        self.assertEqual(result["twse_2021_union_observed_keys"],26120)
        for key,value in (
            ("duplicated_aes_neon_current_stock_date_pairs",551),
            ("previous_pr241_receipt_fully_reauthenticated",False),
            ("historical_point_in_time_universe_verified",True),
            ("prior_2021_aes_source_stock_date_pairs",26120),
        ):
            # Explicitly reject contradictory PIT claims too, if supplied.
            changed=dict(alternate,**{key:value})
            with self.subTest(key=key),self.assertRaises(ValueError):
                overlay.reconcile(changed,b,c)

    def test_duplicate_json_fields_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/"duplicate.json"
            file.write_text('{"scope":"wrong","scope":"right"}',encoding="utf-8")
            with self.assertRaises(ValueError):
                overlay.load(file)

    def test_generated_replacement_delta_and_order_invariance(self):
        rng=random.Random(20261124)
        for _ in range(200):
            a,b,c=fixtures()
            s=b["current_listed_source_date_observation_absence_signatures"]
            delta=rng.randrange(-1000,1001)
            s["nominal_absent_stock_source_date_pairs_inside_first_last"]+=delta
            s["nominal_absent_stock_source_date_pairs_total"]+=delta
            rng.shuffle(c["market"]["twse"]["yearly_neon_source_observations"])
            x=overlay.reconcile(a,b,c)
            self.assertEqual(x["conditional_increment_over_neon_only_baseline"],172274-delta)
            self.assertFalse(x["five_year_history_complete"])

    def test_mutated_receipts_rejected(self):
        for key,val in [("production_neon_writes",True),("schema_version",True),
                        ("model_release","APPROVED"),
                        ("five_year_baseline_window_start","2021-11-24"),
                        ("aes_neon_overlapping_source_stock_date_pairs",551)]:
            a,b,c=fixtures()
            a[key]=val
            with self.subTest(key=key), self.assertRaises(ValueError):
                overlay.reconcile(a,b,c)
        a,b,c=fixtures()
        s=b["current_listed_source_date_observation_absence_signatures"]
        s["nominal_absent_stock_source_date_pairs_total"]-=1
        with self.assertRaises(ValueError):
            overlay.reconcile(a,b,c)
        a,b,c=fixtures()
        c["market"]["twse"]["yearly_neon_source_observations"][1]["year"]=2021
        with self.assertRaises(ValueError):
            overlay.reconcile(a,b,c)

    def test_actual_cli_private_output_is_exclusive_and_repeatable(self):
        script=Path(__file__).resolve().parents[1]/"scripts"/"twse_private_history_receipt_overlay_offline.py"
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            paths=[folder/f"receipt-{i}.json" for i in range(3)]
            for p,r in zip(paths,fixtures()):
                p.write_text(json.dumps(r),encoding="utf-8")
            out=folder/"private-result.json"
            cmd=[sys.executable,str(script),"--union-2021",str(paths[0]),
                 "--density-2022",str(paths[1]),"--neon-five-year",str(paths[2]),
                 "--out",str(out)]
            p=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
            self.assertEqual(p.returncode,0,p.stderr)
            first=out.read_bytes()
            self.assertEqual(len(json.loads(first)["input_receipt_sha256"]),3)
            p=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
            self.assertNotEqual(p.returncode,0)
            self.assertEqual(out.read_bytes(),first)
            cmd[-1]=str(folder/"new-result.json")
            p=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual(Path(cmd[-1]).read_bytes(),first)


if __name__=="__main__":
    unittest.main()
