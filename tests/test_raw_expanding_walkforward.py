"""Purged expanding-folds: only labels matured before each signal are fit."""
from datetime import date
from hashlib import sha256
import json
from unittest import TestCase

from src.raw_expanding_walkforward import expanding_purged_research
from tests.test_raw_factor_walkforward import dataset, input_roster


class ExpandingPurgedTWSEResearchTests(TestCase):
    def test_expanding_purged_dates_and_nonoverlap(self):
        saved = dataset()
        start = input_roster()["1700"][378]["trade_date"]
        result = expanding_purged_research(saved, test_start=start)
        self.assertEqual(result["status"], "RETROSPECTIVE_EXPANDING_PURGED_RAW_ONLY")
        self.assertGreater(result["count"], 1)
        self.assertFalse(result["research_window_count_sufficient"])
        self.assertTrue(result["training_is_purged_by_actual_exit"])
        self.assertFalse(result["independent_future_validation_passed"])
        self.assertFalse(result["price_labels_adjusted_for_dividends"])
        self.assertEqual(result["neon_database_writes"], 0)
        self.assertFalse(result["trading_approved"])
        for i, sample in enumerate(result["nonoverlap_windows"]):
            self.assertLess(sample["last_mature_training_exit"], sample["signal_date"])
            self.assertLess(sample["signal_date"], sample["entry_date"])
            self.assertLess(sample["entry_date"], sample["exit_date"])
            self.assertGreaterEqual(sample["training_date_count"], 20)
            self.assertGreaterEqual(sample["training_row_count"], 100)
            self.assertAlmostEqual(
                sample["assumed_net_excess_vs_equal_weight"],
                sample["assumed_cost_net_return"] -
                sample["equal_weight_assumed_cost_net_return"],
                places=9,
            )
            if i:
                self.assertLess(result["nonoverlap_windows"][i-1]["exit_date"],
                                sample["signal_date"])

    def test_future_holdout_mutation_does_not_change_first_fold_training(self):
        original = dataset()
        start = input_roster()["1700"][378]["trade_date"]
        control = expanding_purged_research(original, test_start=start)
        trial = json.loads(json.dumps(original))
        last_signal = max(x["as_of_date"] for x in trial["rows"])
        for sample in trial["rows"]:
            if sample["as_of_date"] == last_signal:
                sample["raw_unadjusted_gross_return"] = -0.5
        trial["rows_sha256"] = sha256(
            json.dumps(trial["rows"],sort_keys=True,separators=(",",":"),
                       allow_nan=False).encode()
        ).hexdigest()
        changed = expanding_purged_research(trial, test_start=start)
        self.assertEqual(
            control["nonoverlap_windows"][0]["training_weights_sha256"],
            changed["nonoverlap_windows"][0]["training_weights_sha256"],
        )
        self.assertEqual(
            control["nonoverlap_windows"][0]["assumed_cost_net_return"],
            changed["nonoverlap_windows"][0]["assumed_cost_net_return"],
        )
        self.assertFalse(changed["independent_future_validation_passed"])

    def test_tampered_rows_still_fail_closed(self):
        d = dataset()
        d["rows"][0]["feature_vector"][0] += 1
        with self.assertRaises(ValueError):
            expanding_purged_research(d, test_start=date(2026,1,1))
