"""Semantic receipt checks and input-order invariance on synthetic research data."""
from copy import deepcopy
from datetime import date
from hashlib import sha256
import json
import random
from unittest import TestCase

from src.raw_factor_walkforward import purged_ridge_prototype
from src.raw_expanding_walkforward import expanding_purged_research
from tests.test_raw_factor_walkforward import dataset, input_roster


def rehash(d):
    d["rows_sha256"]=sha256(json.dumps(d["rows"],sort_keys=True,
        separators=(",",":"),allow_nan=False).encode()).hexdigest()
    return d


class RawReceiptValidationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt=dataset()
        cls.start=input_roster()["1700"][378]["trade_date"]

    def test_rehashed_invalid_receipts_rejected_by_both_engines(self):
        def mixed_market(d):
            d["rows"][0]["market"]="twse"
        def banned(d):
            sid=d["frozen_current_stock_roster"][0]
            d["frozen_current_stock_roster"][0]="1589"
            for row in d["rows"]:
                if row["stock_id"]==sid:
                    row["stock_id"]="1589"
        def duplicate(d):
            d["frozen_current_stock_roster"].append(d["frozen_current_stock_roster"][0])
        def wrong_label(d):
            d["rows"][0]["forward_label_is_unadjusted_price_only"]=False
        def impossible_return(d):
            d["rows"][0]["raw_unadjusted_gross_return"]=-1.01
        def bool_return(d):
            d["rows"][0]["raw_unadjusted_gross_return"]=True
        def excess_return(d):
            d["rows"][0]["raw_unadjusted_gross_return"]=10.01
        def wrong_count(d):
            d["requested_signal_days"]+=1
        def wrong_version(d):
            d["feature_version"]="unverified"
        def wrong_date(d):
            d["rows"][0]["entry_date"]=d["rows"][0]["entry_date"].replace("-","")
        for mutation in (mixed_market,banned,duplicate,wrong_label,impossible_return,
                         bool_return,excess_return,wrong_count,wrong_version,wrong_date):
            damaged=deepcopy(self.receipt)
            mutation(damaged)
            rehash(damaged)
            for engine in (purged_ridge_prototype,expanding_purged_research):
                with self.subTest(mutation=mutation.__name__,engine=engine.__name__):
                    with self.assertRaises(ValueError):
                        engine(damaged,test_start=self.start)

    def test_tied_scores_are_invariant_under_seeded_row_permutations(self):
        d=deepcopy(self.receipt)
        for row in d["rows"]:
            row["feature_vector"]=[0.0]*len(d["feature_names"])
            # Distinct synthetic label by issuer; tied scores must use stock ID,
            # never row order or the forward outcome as a tiebreak.
            row["raw_unadjusted_gross_return"]=(int(row["stock_id"])-1700)*.01
        rehash(d)
        fixed=purged_ridge_prototype(d,test_start=self.start)
        growing=expanding_purged_research(d,test_start=self.start)
        self.assertGreater(fixed["nonoverlap_count"],0)
        self.assertGreater(growing["count"],0)
        # Six stocks, top 20% rounds up to two; first two have returns 0 and .01.
        for window in fixed["nonoverlap_test_windows"]:
            self.assertAlmostEqual(window["raw_price_only_gross_return"],.005)
        for seed in (1,2,3,4,5,6,7,8):
            shuffled=deepcopy(d)
            random.Random(seed).shuffle(shuffled["rows"])
            rehash(shuffled)
            p=purged_ridge_prototype(shuffled,test_start=self.start)
            e=expanding_purged_research(shuffled,test_start=self.start)
            self.assertEqual(p["nonoverlap_test_windows"],fixed["nonoverlap_test_windows"])
            self.assertEqual(p["prototype_weights_from_mature_development_only"],
                             fixed["prototype_weights_from_mature_development_only"])
            self.assertEqual(e["nonoverlap_windows"],growing["nonoverlap_windows"])
            self.assertFalse(e["independent_future_validation_passed"])
            self.assertFalse(e["trading_approved"])
