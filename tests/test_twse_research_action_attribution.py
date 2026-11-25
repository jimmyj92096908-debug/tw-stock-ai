"""Offline determinism tests for fixed/expanding replay and dividend-window labels."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from hashlib import sha256
import json
import random
import unittest

from src.raw_factor_feature_bridge import FEATURE_NAMES
from src.raw_factor_walkforward import purged_ridge_prototype
from src.raw_expanding_walkforward import expanding_purged_research
from scripts.twse_research_action_attribution import attribute, replay
from scripts.twse_official_research_action_reconcile import validate_study


def fixture():
    roster = [str(1100 + i) for i in range(20)]
    development = [date(2026, 1, 2) + timedelta(days=3*i) for i in range(30)]
    holdout = [date(2026, 8, 10) + timedelta(days=10*i) for i in range(10)]
    rows = []
    for n, signal in enumerate(development + holdout):
        entry = signal + timedelta(days=1)
        exit_day = signal + timedelta(days=6)
        for idx, sid in enumerate(roster):
            features = [
                round(((n*(j+3) + idx*(j+5) + j*7) % 29)/30.0 + n/10000, 9)
                for j in range(len(FEATURE_NAMES))
            ]
            rows.append({
                "as_of_date": signal.isoformat(), "market": "twse", "stock_id": sid,
                "feature_vector": features, "entry_date": entry.isoformat(),
                "exit_date": exit_day.isoformat(),
                "forward_label_is_unadjusted_price_only": True,
                "raw_unadjusted_gross_return":
                    round(-0.025 + 0.0015*idx + 0.0006*(n % 7)
                          + (0.002 if idx % 3 == 0 else -0.001), 12),
            })
    digest = sha256(json.dumps(rows, sort_keys=True, separators=(",", ":"),
                               allow_nan=False).encode()).hexdigest()
    dataset = {
        "schema_version": 1, "feature_version": "tw-raw-price-asof-bridge-1",
        "requested_signal_days": len(development) + len(holdout),
        "accepted_whole_cohort_days": len(development) + len(holdout),
        "excluded_whole_cohort_days": {},
        "market": "twse", "research_status":
            "RAW_ONLY_UNADJUSTED_SOURCE_COHORT_NOT_A_MODEL_RELEASE",
        "feature_names": list(FEATURE_NAMES),
        "frozen_current_stock_roster": roster, "rows": rows,
        "rows_sha256": digest, "label_cutoff": "2026-11-15",
        "existing_tw_factor_ridge_1_feature_schema_compatible": False,
        "price_labels_adjusted_for_cash_dividends_or_splits": False,
    }
    fixed = purged_ridge_prototype(dataset, test_start=holdout[0])
    expanding = expanding_purged_research(dataset, test_start=holdout[0])
    windows = fixed["nonoverlap_test_windows"]
    readiness = {
        "release_decision": "BLOCKED",
        "historical_total_return_labels_verified": False,
        "research_stocks": 20, "research_windows": 10,
        "entry_date_min": windows[0]["entry_date"],
        "exit_date_max": windows[-1]["exit_date"],
        "database_read_only": True, "database_writes": 0, "line_messages_sent": 0,
    }
    first = windows[0]
    events = [
        {"stock_id": roster[0], "ex_date": first["signal_date"],
         "action_type_candidate": "CASH_DIVIDEND",
         "explicit_cash_dividend_per_share": None,
         "reference_price_factor_if_available": 0.965},
        {"stock_id": roster[1], "ex_date": first["exit_date"],
         "action_type_candidate": "CASH_DIVIDEND",
         "explicit_cash_dividend_per_share": None,
         "reference_price_factor_if_available": 0.995},
    ]
    overlap = []
    for w in windows:
        matched = [a for a in events
                   if w["entry_date"] <= a["ex_date"] <= w["exit_date"]]
        overlap.append({
            "signal_date": w["signal_date"], "entry_date": w["entry_date"],
            "exit_date": w["exit_date"],
            "official_candidate_events_near_holding_period": len(matched),
            "stocks_with_candidates": sorted({a["stock_id"] for a in matched}),
        })
    official = {
        "scope": "TWSE_20_STOCK_OFFICIAL_EX_ACTION_CANDIDATE_RECONCILIATION",
        "release_decision": "BLOCKED",
        "true_total_return_label_verified": False,
        "database_connections": 0, "database_writes": 0,
        "line_messages_sent": 0,
        "monthly_source_files_not_independently_authenticated": True,
        "historical_issuer_announcement_vintage_verified": False,
        "historical_point_in_time_universe_verified": False,
        "twse_research_cohort_candidate_events": 2,
        "candidate_events": events, "window_candidate_overlap": overlap,
        "research_windows_with_event_candidate": 1,
    }
    return dataset, fixed, expanding, readiness, official


class ActionAttributionTests(unittest.TestCase):
    def test_replay_all_saved_fixed_and_expanding_evaluations(self):
        d, f, e, ready, official = fixture()
        roster, windows, _ = validate_study(d, f, e, ready)
        picks = replay(d, f, e, windows)
        self.assertEqual(len(picks), 10)
        for w in windows:
            a = picks[w["signal_date"]]
            self.assertEqual(len(a["fixed_selected_stocks"]), 4)
            self.assertEqual(len(a["expanding_selected_stocks"]), 4)
            self.assertEqual(len(set(a["fixed_selected_stocks"])), 4)
            self.assertTrue(set(a["expanding_selected_stocks"]) <= roster)

    def test_replay_is_invariant_to_rehashed_row_order(self):
        d, f, e, ready, official = fixture()
        _, windows, _ = validate_study(d, f, e, ready)
        expected = replay(d, f, e, windows)
        for seed in (17, 29, 41):
            shuffled = deepcopy(d)
            random.Random(seed).shuffle(shuffled["rows"])
            shuffled["rows_sha256"] = sha256(json.dumps(
                shuffled["rows"], sort_keys=True, separators=(",", ":"),
                allow_nan=False).encode()).hexdigest()
            self.assertEqual(replay(shuffled, f, e, windows), expected)

    def test_signal_date_is_not_held_and_exit_date_is_flagged(self):
        d, f, e, ready, official = fixture()
        result = attribute(d, f, e, ready, official)
        self.assertEqual(result["original_nonoverlap_windows_replayed"], 10)
        self.assertEqual(result["candidate_events_reviewed"], 2)
        self.assertEqual(result["release_decision"], "BLOCKED")
        self.assertEqual(result["database_connections"], 0)
        self.assertEqual(result["database_writes"], 0)
        self.assertEqual(result["line_messages_sent"], 0)
        self.assertFalse(result["total_return_labels_recomputed"])
        sig = result["events"][0]["signal_or_holding_windows"][0]
        self.assertTrue(sig["ex_date_on_signal_day_before_entry"])
        self.assertFalse(sig["ex_date_inside_holding_inclusive"])
        ex = result["events"][1]["signal_or_holding_windows"][0]
        self.assertTrue(ex["ex_date_on_exit_day"])
        self.assertTrue(ex["ex_date_inside_holding_inclusive"])
        self.assertFalse(ex["confirmed_dividend_cash_entitlement"])
        self.assertFalse(ex["label_return_adjustment_permitted"])

    def test_absent_cash_not_replaced_with_reference_factor(self):
        d, f, e, ready, official = fixture()
        result = attribute(d, f, e, ready, official)
        self.assertIsNone(result["events"][1]["explicit_cash_dividend_per_share"])
        self.assertEqual(result["events"][1]["reference_price_factor_if_available"], 0.995)
        self.assertTrue(result["events"][1][
            "reference_factor_is_not_cash_dividend_per_share"])
        self.assertFalse(result["dividend_proceeds_calculated"])

    def test_saved_fixed_model_return_tampering_fails(self):
        d, f, e, ready, official = fixture()
        f["nonoverlap_test_windows"][0]["raw_price_only_gross_return"] = 999
        with self.assertRaisesRegex(ValueError, "fixed-gross"):
            attribute(d, f, e, ready, official)

    def test_expanding_fold_weight_hash_tampering_fails(self):
        d, f, e, ready, official = fixture()
        e["nonoverlap_windows"][0]["training_weights_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Expanding coefficients"):
            attribute(d, f, e, ready, official)

    def test_frozen_roster_exclusions_and_checksum_rejected(self):
        d, f, e, ready, official = fixture()
        d["frozen_current_stock_roster"][0] = "1589"
        with self.assertRaises(ValueError):
            attribute(d, f, e, ready, official)
        d, f, e, ready, official = fixture()
        d["rows"][0]["raw_unadjusted_gross_return"] = 1.0
        with self.assertRaises(ValueError):
            attribute(d, f, e, ready, official)

    def test_unsupported_source_or_approved_release_is_rejected(self):
        d, f, e, ready, official = fixture()
        official["release_decision"] = "APPROVED"
        with self.assertRaises(ValueError):
            attribute(d, f, e, ready, official)
        d, f, e, ready, official = fixture()
        official["candidate_events"][0]["stock_id"] = "1589"
        with self.assertRaises(ValueError):
            attribute(d, f, e, ready, official)

    def test_mismatched_overlap_and_false_event_count_rejected(self):
        d, f, e, ready, official = fixture()
        official["window_candidate_overlap"][0]["stocks_with_candidates"] = []
        with self.assertRaisesRegex(ValueError, "overlap"):
            attribute(d, f, e, ready, official)
        d, f, e, ready, official = fixture()
        official["twse_research_cohort_candidate_events"] = 3
        with self.assertRaises(ValueError):
            attribute(d, f, e, ready, official)

    def test_changes_to_label_after_receipt_are_not_silently_reclassified(self):
        d, f, e, ready, official = fixture()
        official["candidate_events"][1]["ex_date"] = official["candidate_events"][0]["ex_date"]
        with self.assertRaises(ValueError):
            attribute(d, f, e, ready, official)


if __name__ == "__main__":
    unittest.main()
