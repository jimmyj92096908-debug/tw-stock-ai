"""Offline fail-closed coverage tests: never connect to Neon or send LINE."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from hashlib import sha256
import json
import unittest

from scripts.twse_research_total_return_readiness import (
    ACTION_SQL, PRICE_SQL, evaluate, validate_artifacts,
)


def evidence():
    roster = [str(1100 + i) for i in range(20)]
    rows, fw, ew = [], [], []
    first = date(2026, 8, 10)
    for i in range(10):
        signal = first + timedelta(days=i * 10)
        entry = signal + timedelta(days=1)
        exit_day = signal + timedelta(days=6)
        fixed = {
            "signal_date": signal.isoformat(),
            "entry_date": entry.isoformat(),
            "exit_date": exit_day.isoformat(),
        }
        fw.append(fixed)
        ew.append({
            **fixed,
            "last_mature_training_exit": (signal - timedelta(days=1)).isoformat(),
        })
        for sid in roster:
            rows.append({
                "as_of_date": signal.isoformat(),
                "market": "twse",
                "stock_id": sid,
                "entry_date": entry.isoformat(),
                "exit_date": exit_day.isoformat(),
            })
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode()
    dataset = {
        "market": "twse",
        "frozen_current_stock_roster": roster,
        "rows": rows,
        "rows_sha256": sha256(encoded).hexdigest(),
        "price_labels_adjusted_for_cash_dividends_or_splits": False,
    }
    fixed = {
        "label_is_adjusted_total_return": False,
        "nonoverlap_test_windows": fw,
    }
    expanding = {
        "price_labels_adjusted_for_dividends": False,
        "nonoverlap_windows": ew,
    }
    return dataset, fixed, expanding


def counts():
    return {
        "raw_price_keys": 1400,
        "derived_price_keys": 1400,
        "unadjusted_keys": 1400,
        "missing_adjustment_status": 0,
        "other_adjustment_status_keys": 0,
        "different_close_keys": 0,
        "stock_count": 20,
    }, {
        "stored_event_rows": 0,
        "verified_event_rows": 0,
        "unverified_event_rows": 0,
        "first_stored_after_ex_date": 0,
    }


class TotalReturnReadinessTests(unittest.TestCase):
    def test_realistic_unadjusted_database_stays_blocked(self):
        d, f, e = evidence()
        roster, start, end = validate_artifacts(d, f, e)
        p, a = counts()
        result = evaluate(roster, start, end, p, a)
        self.assertEqual(result["release_decision"], "BLOCKED")
        self.assertFalse(result["historical_total_return_labels_verified"])
        self.assertFalse(result["absence_of_stored_actions_proves_no_real_dividends"])
        self.assertFalse(result["derived_prices_prove_cash_total_returns"])
        self.assertEqual(result["database_writes"], 0)
        self.assertEqual(result["line_messages_sent"], 0)
        self.assertEqual(result["research_windows"], 10)

    def test_even_adjusted_statuses_and_verified_actions_cannot_fake_pit(self):
        d, f, e = evidence()
        roster, start, end = validate_artifacts(d, f, e)
        p, a = counts()
        p["unadjusted_keys"] = 0
        p["other_adjustment_status_keys"] = 1400
        p["different_close_keys"] = 300
        a["stored_event_rows"] = 20
        a["verified_event_rows"] = 20
        result = evaluate(roster, start, end, p, a)
        self.assertFalse(result["original_issuer_publication_vintage_verified"])
        self.assertFalse(result["historical_total_return_labels_verified"])
        self.assertEqual(result["release_decision"], "BLOCKED")

    def test_bad_cohort_or_excluded_stock_fails_closed(self):
        d, f, e = evidence()
        d["frozen_current_stock_roster"][0] = "1589"
        with self.assertRaises(ValueError):
            validate_artifacts(d, f, e)
        d, f, e = evidence()
        d["frozen_current_stock_roster"].append(d["frozen_current_stock_roster"][0])
        with self.assertRaises(ValueError):
            validate_artifacts(d, f, e)

    def test_modified_source_fingerprint_fails_closed(self):
        d, f, e = evidence()
        d["rows"][0]["stock_id"] = "1589"
        with self.assertRaises(ValueError):
            validate_artifacts(d, f, e)

    def test_window_alignment_and_future_training_leak_fail(self):
        d, f, e = evidence()
        e["nonoverlap_windows"][0]["exit_date"] = "2026-08-21"
        with self.assertRaises(ValueError):
            validate_artifacts(d, f, e)
        d, f, e = evidence()
        e["nonoverlap_windows"][0]["last_mature_training_exit"] = "2026-08-10"
        with self.assertRaises(ValueError):
            validate_artifacts(d, f, e)

    def test_unadjusted_labels_must_not_be_claimed_adjusted(self):
        d, f, e = evidence()
        d["price_labels_adjusted_for_cash_dividends_or_splits"] = True
        with self.assertRaises(ValueError):
            validate_artifacts(d, f, e)

    def test_db_counts_must_be_consistent(self):
        d, f, e = evidence()
        roster, start, end = validate_artifacts(d, f, e)
        p, a = counts()
        p["derived_price_keys"] = 1401
        with self.assertRaises(ValueError):
            evaluate(roster, start, end, p, a)
        p, a = counts()
        p["stock_count"] = 19
        with self.assertRaises(ValueError):
            evaluate(roster, start, end, p, a)
        p, a = counts()
        a["verified_event_rows"] = 1
        with self.assertRaises(ValueError):
            evaluate(roster, start, end, p, a)

    def test_sql_is_aggregated_read_only_and_scoped(self):
        for statement in (PRICE_SQL, ACTION_SQL):
            self.assertTrue(statement.strip().startswith("SELECT"))
            self.assertIn("market='twse'", statement)
            self.assertIn("stock_id=ANY", statement)
            self.assertIn("BETWEEN", statement)
            for banned in ("UPDATE ", "DELETE ", "INSERT ", "DROP ", "CREATE "):
                self.assertNotIn(banned, statement.upper())


if __name__ == "__main__":
    unittest.main()
