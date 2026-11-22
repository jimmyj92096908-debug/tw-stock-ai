"""Offline regressions for dated 2022 dividends absent from 2327/2603 Neon."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.twse_2022_known_dividend_gap_offline import (
    SCOPE, classify_historical_dividend_gaps,
)


def prior(stored_2327=0, stored_2603=0):
    rows = []
    for sid, n in (("2327", stored_2327), ("2603", stored_2603)):
        rows.append({
            "stock_id": sid,
            "stored_event_rows_in_proven_240_traded_day_window": n,
            "stored_verified_event_rows": n,
            "stored_unverified_event_rows": 0,
            "stored_cash_dividend_rows": n,
            "stored_cash_dividend_rows_missing_amount": 0,
            "stored_non_cash_reduction_event_rows": n,
            "no_stored_event_means_no_real_dividend": False,
            "full_corporate_action_and_dividend_history_verified": False,
        })
    return {
        "schema_version": 1,
        "scope": "OWNER_ONLY_2022_TWSE_FROZEN2_CORPORATE_ACTION_COVERAGE_AUDIT",
        "live_model_release_decision": "BLOCKED",
        "source_window_start": "2021-12-30",
        "source_window_end": "2022-12-30",
        "original_asof_issuer_publication_vintage_verified": False,
        "independently_complete_historical_dividends_and_splits": False,
        "cash_reduction_only_sma240_is_complete_total_return": False,
        "production_neon_writes": 0,
        "line_messages_sent": 0,
        "actual_readonly_stored_action_rows": stored_2327 + stored_2603,
        "per_stock_action_coverage": rows,
    }


class KnownDividendGapOfflineTests(unittest.TestCase):
    def test_actual_zero_stored_events_proves_two_specific_missing_events(self):
        r = classify_historical_dividend_gaps(prior())
        self.assertEqual(r["scope"], SCOPE)
        self.assertEqual(r["independently_dated_2022_cash_dividend_events"], 2)
        self.assertEqual(
            r["events_confirmed_missing_from_prior_neon_cash_dividend_inventory"], 2)
        by = {x["stock_id"]: x for x in r["per_stock_known_dividend_event_gaps"]}
        self.assertEqual(by["2327"]["known_historical_cash_dividend_ex_date"],
                         "2022-07-04")
        self.assertEqual(by["2603"]["known_historical_cash_dividend_ex_date"],
                         "2022-06-29")
        for row in by.values():
            self.assertTrue(row["dated_event_vs_prior_neon_status"].startswith(
                "CONFIRMED_MISSING"))
            self.assertEqual(len(row["contemporaneous_public_event_evidence"]), 2)
            self.assertFalse(row["precise_per_share_cash_amount_certified"])
            self.assertFalse(row["historical_dividend_event_insert_permitted"])
            self.assertFalse(row["stock_price_factor_or_sma240_recomputed"])
        self.assertEqual(r["production_neon_writes"], 0)
        self.assertEqual(r["line_messages_sent"], 0)
        self.assertEqual(r["live_model_release_decision"], "BLOCKED")

    def test_nonzero_aggregate_cash_rows_cannot_prove_exact_date_is_stored(self):
        r = classify_historical_dividend_gaps(prior(1, 2))
        self.assertEqual(
            r["events_confirmed_missing_from_prior_neon_cash_dividend_inventory"], 0)
        for e in r["per_stock_known_dividend_event_gaps"]:
            self.assertEqual(e["dated_event_vs_prior_neon_status"],
                             "EXACT_EX_DATE_MATCH_UNPROVEN_NEEDS_TARGETED_READONLY_QUERY")
        self.assertFalse(r["fully_adjusted_sma240_or_true_total_return_approved"])

    def test_only_one_zero_stock_still_flags_one_missed_event(self):
        r = classify_historical_dividend_gaps(prior(0, 1))
        self.assertEqual(
            r["events_confirmed_missing_from_prior_neon_cash_dividend_inventory"], 1)
        self.assertEqual([e["stock_id"] for e in r["per_stock_known_dividend_event_gaps"]],
                         ["2327", "2603"])

    def test_inconsistent_or_modified_original_release_rejected(self):
        for key, value in (
            ("schema_version", 0), ("scope", "UNVERIFIED"),
            ("live_model_release_decision", "APPROVED"),
            ("production_neon_writes", 1),
            ("source_window_end", "2023-01-01"),
            ("cash_reduction_only_sma240_is_complete_total_return", True),
        ):
            bad = prior()
            bad[key] = value
            with self.assertRaises(ValueError, msg=key):
                classify_historical_dividend_gaps(bad)

    def test_partial_inconsistent_duplicate_stock_and_unverified_claims_refused(self):
        bad = prior()
        bad["actual_readonly_stored_action_rows"] = 1
        with self.assertRaises(ValueError):
            classify_historical_dividend_gaps(bad)
        bad = prior()
        bad["per_stock_action_coverage"][1]["stock_id"] = "2327"
        with self.assertRaises(ValueError):
            classify_historical_dividend_gaps(bad)
        bad = prior()
        bad["per_stock_action_coverage"][0]["no_stored_event_means_no_real_dividend"] = True
        with self.assertRaises(ValueError):
            classify_historical_dividend_gaps(bad)

    def test_cli_no_database_url_and_never_overwrites_owner_private_report(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "prior-action-coverage.json"
            target = Path(folder) / "dated-ex-dividend-gaps.json"
            source.write_text(json.dumps(prior()), encoding="utf-8")
            env = os.environ.copy()
            env.pop("DATABASE_URL", None)
            env.pop("STOCK_ARCHIVE_KEY_HEX", None)
            env.pop("PYTHONPATH", None)
            cmd = [sys.executable, "-m",
                   "scripts.twse_2022_known_dividend_gap_offline",
                   "--prior-action-report", str(source), "--out", str(target)]
            run = subprocess.run(cmd, cwd=root, env=env, capture_output=True,
                                 text=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("TWO_STOCK_2022_KNOWN_DIVIDEND_GAP_OFFLINE_PASS",
                          run.stdout)
            content = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(
                content["events_confirmed_missing_from_prior_neon_cash_dividend_inventory"],
                2)
            self.assertEqual(content["live_model_release_decision"], "BLOCKED")
            again = subprocess.run(cmd, cwd=root, env=env, capture_output=True,
                                   text=True, timeout=20)
            self.assertNotEqual(again.returncode, 0)
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8"))["production_neon_writes"],
                0)


if __name__ == "__main__":
    unittest.main()
