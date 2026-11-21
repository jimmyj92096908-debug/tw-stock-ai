"""RAW-only offline factor cohorts and purged exploratory ridge cannot approve alpha."""
from __future__ import annotations

from datetime import date,timedelta
from hashlib import sha256
import json
from unittest import TestCase

from src.raw_factor_walkforward import frozen_unadjusted_dataset,purged_ridge_prototype
from src.raw_factor_feature_bridge import FEATURE_NAMES

def source(n=490,code="1742",offset=0):
    base=date(2025,1,2)
    result=[]
    for i in range(n):
        v=50+offset+(i+1)*0.08+((i*7+offset)%13)*0.11
        result.append({"market":"tpex","stock_id":code,
                       "trade_date":base+timedelta(days=i),
                       "open":v-0.20,"high":v+1.2,"low":v-1.2,
                       "close":v,"volume":1000+10*i+offset,
                       "source":"TPEX_DATED_OTC_EW"})
    return result

def input_roster():
    return {str(1700+i):source(code=str(1700+i),offset=i) for i in range(6)}

def sigs(bars):
    return [bars[j]["trade_date"] for j in range(250,426,5)]

def dataset():
    roster=input_roster()
    return frozen_unadjusted_dataset(roster,
        signal_dates=sigs(next(iter(roster.values()))),
        label_cutoff=date(2026,6,30))

class RawFactorOfflineWalkforwardTests(TestCase):
    def test_whole_roster_full_price_labels_and_no_release(self):
        d=dataset()
        self.assertEqual(d["accepted_whole_cohort_days"],36)
        self.assertEqual(len(d["rows"]),216)
        self.assertEqual(d["frozen_current_stock_roster"],sorted(input_roster()))
        self.assertEqual(d["feature_names"],list(FEATURE_NAMES))
        self.assertTrue(d["rows"][0]["forward_label_is_unadjusted_price_only"])
        self.assertFalse(d["price_labels_adjusted_for_cash_dividends_or_splits"])
        self.assertFalse(d["issuer_population_survivorship_audited"])
        self.assertFalse(d["existing_tw_factor_ridge_1_feature_schema_compatible"])
        self.assertFalse(d["live_trading_approved"])
        self.assertEqual(d["database_writes"],0)

    def test_future_prices_cannot_affect_pre_signal_features(self):
        stock=input_roster()
        before=frozen_unadjusted_dataset(stock,signal_dates=[
            next(iter(stock.values()))[270]["trade_date"]],
            label_cutoff=date(2026,6,30))
        replacement=input_roster()
        # Change only the forward EXIT day, not both entry and exit,
        # so the label must change while the as-of features remain identical.
        p=replacement["1700"][276]
        p["close"]*=1.05
        p["open"]*=1.05
        p["high"]*=1.05
        p["low"]*=1.05
        after=frozen_unadjusted_dataset(replacement,signal_dates=[
            next(iter(stock.values()))[270]["trade_date"]],
            label_cutoff=date(2026,6,30))
        a=next(x for x in before["rows"] if x["stock_id"]=="1700")
        b=next(x for x in after["rows"] if x["stock_id"]=="1700")
        self.assertEqual(a["feature_vector"],b["feature_vector"])
        self.assertNotEqual(a["raw_unadjusted_gross_return"],
                            b["raw_unadjusted_gross_return"])

    def test_missing_one_stock_label_excludes_every_stock_on_that_day(self):
        stock=input_roster()
        signal=stock["1700"][300]["trade_date"]
        original=frozen_unadjusted_dataset(stock,signal_dates=[signal],
                                          label_cutoff=date(2026,6,30))
        self.assertEqual(original["accepted_whole_cohort_days"],1)
        stock["1702"].pop(306)
        damaged=frozen_unadjusted_dataset(stock,signal_dates=[signal],
                                         label_cutoff=date(2026,6,30))
        self.assertEqual(damaged["accepted_whole_cohort_days"],0)
        self.assertEqual(damaged["rows"],[])
        self.assertEqual(damaged["excluded_whole_cohort_days"],
                         {"unaligned_real_stock_trading_windows":1})
        stock=input_roster()
        stock["1703"]=stock["1703"][:304]
        failed=frozen_unadjusted_dataset(stock,signal_dates=[signal],
                                         label_cutoff=date(2026,6,30))
        self.assertEqual(failed["rows"],[])
        self.assertEqual(failed["excluded_whole_cohort_days"],
                         {"unmatured_next_session_to_exit_label":1})

    def test_development_only_ridge_and_future_holdout_never_approved(self):
        d=dataset()
        first=d["rows"][0]["as_of_date"]
        test_start=input_roster()["1700"][378]["trade_date"]
        r=purged_ridge_prototype(d,test_start=test_start)
        self.assertEqual(r["status"],"RETROSPECTIVE_EXPLORATORY_UNADJUSTED_PRICE_ONLY")
        self.assertGreaterEqual(r["development_dates"],20)
        self.assertGreaterEqual(r["development_rows"],100)
        self.assertGreater(r["nonoverlap_count"],0)
        self.assertTrue(r["purged_train_label_exits_before_first_holdout"])
        self.assertTrue(r["training_features_scaled_using_only_mature_development_rows"])
        self.assertFalse(r["label_is_adjusted_total_return"])
        self.assertFalse(r["source_capture_vintage_proven"])
        self.assertFalse(r["may_update_production_model_weights"])
        self.assertFalse(r["may_release_positive_alpha_or_trade_signals"])
        self.assertFalse(r["live_trading_approved"])
        for n,a in enumerate(r["nonoverlap_test_windows"]):
            self.assertLess(a["signal_date"],a["entry_date"])
            self.assertLess(a["entry_date"],a["exit_date"])
            if n:
                self.assertLess(r["nonoverlap_test_windows"][n-1]["exit_date"],
                                a["signal_date"])

        # Manipulate only holdout labels, retaining checksum: training model
        # weights MUST remain byte-for-byte identical.
        modified=json.loads(json.dumps(d))
        for x in modified["rows"]:
            if x["as_of_date"]>=test_start.isoformat():
                x["raw_unadjusted_gross_return"]=-0.5
        modified["rows_sha256"]=sha256(json.dumps(modified["rows"],sort_keys=True,
                    separators=(",",":"),allow_nan=False).encode()).hexdigest()
        trial=purged_ridge_prototype(modified,test_start=test_start)
        self.assertEqual(r["prototype_weights_from_mature_development_only"],
                         trial["prototype_weights_from_mature_development_only"])

    def test_tampering_or_insufficient_cohorts_never_claim_release(self):
        d=dataset()
        d["rows"][0]["feature_vector"][0]+=1
        with self.assertRaises(ValueError):
            purged_ridge_prototype(d,test_start=date(2026,1,1))
        small=frozen_unadjusted_dataset(input_roster(),signal_dates=[
            input_roster()["1700"][280]["trade_date"]],
            label_cutoff=date(2026,6,30))
        result=purged_ridge_prototype(small,
                test_start=input_roster()["1700"][280]["trade_date"])
        self.assertEqual(result["status"],"INSUFFICIENT_MATURE_RAW_SOURCE_RESEARCH")
        self.assertFalse(result["may_update_production_model_weights"])
        with self.assertRaises(ValueError):
            purged_ridge_prototype(small,test_start=date(2030,1,1))
        with self.assertRaises(ValueError):
            frozen_unadjusted_dataset(input_roster(),signal_dates=[
                date(2030,1,1)],label_cutoff=date(2026,6,30))
