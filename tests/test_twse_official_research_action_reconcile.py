"""Isolated offline tests of official ex-action preview vs frozen 20-stock research."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from hashlib import sha256
import json
import unittest

from scripts.twse_official_research_action_reconcile import (
    EXACT_SOURCES, inspect_month, month_windows, reconcile, validate_study,
)


def fake_study():
    roster = [str(1100 + i) for i in range(19)] + ["2308"]
    fw, ew, rows = [], [], []
    first = date(2026, 8, 10)
    for i in range(10):
        signal = first + timedelta(days=10 * i)
        entry = signal + timedelta(days=1)
        exit_day = signal + timedelta(days=6)
        f = {"signal_date": signal.isoformat(), "entry_date": entry.isoformat(), "exit_date": exit_day.isoformat()}
        fw.append(f)
        ew.append({**f, "last_mature_training_exit": (signal - timedelta(days=1)).isoformat()})
        for sid in roster:
            rows.append({"as_of_date": signal.isoformat(), "stock_id": sid,
                         "entry_date": entry.isoformat(), "exit_date": exit_day.isoformat()})
    digest = sha256(json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    d = {"market": "twse", "frozen_current_stock_roster": roster, "rows": rows,
         "rows_sha256": digest,
         "price_labels_adjusted_for_cash_dividends_or_splits": False}
    f = {"nonoverlap_test_windows": fw, "label_is_adjusted_total_return": False}
    e = {"nonoverlap_windows": ew, "price_labels_adjusted_for_dividends": False}
    read = {"release_decision": "BLOCKED", "historical_total_return_labels_verified": False,
            "research_stocks": 20, "research_windows": 10,
            "entry_date_min": fw[0]["entry_date"], "exit_date_max": fw[-1]["exit_date"],
            "database_read_only": True, "database_writes": 0, "line_messages_sent": 0}
    return d, f, e, read


def fake_month(start, end, candidates=()):
    ev = []
    for (market, kind), sources in EXACT_SOURCES.items():
        n = sum(e["market"] == market and (kind == "reduction") ==
                (e["action_type_candidate"] == "CAPITAL_REDUCTION") for e in candidates)
        ev.append({"market": market, "kind": kind, "source": sorted(sources)[0],
                   "received_rows": n, "four_digit_candidates": n,
                   "excluded_outside_requested_date_range": 0,
                   "excluded_non_common_stock_or_unknown": 0})
    return {
        "schema_version": 1,
        "scope": "TWSE_TPEX_CURRENT_OFFICIAL_EXRIGHT_MONTHLY_EVIDENCE_NOT_TOTAL_RETURN",
        "query_from": start.isoformat(), "query_to": end.isoformat(),
        "first_seen_at_utc": "2026-11-22T13:00:00+00:00",
        "source_evidence": ev,
        "raw_four_digit_source_events": len(candidates),
        "distinct_candidate_economic_events": len(candidates),
        "duplicate_economic_feed_records": 0,
        "candidates": list(candidates),
        "verified_total_return_labels": False,
        "raw_price_labels_still_unadjusted": True,
        "no_historical_issuer_publication_vintages_in_feed": True,
        "not_full_five_year_issuer_or_dividend_coverage": True,
        "production_corporate_actions_modified": False,
        "database_writes": 0,
        "LINE_or_trading_enabled": False,
        "paid_data_used": False,
    }


def fake_candidate(stock_id="2308", ex_date="2026-11-10", *, market="twse",
                   kind="CASH_DIVIDEND", cash=2.5):
    source = ("https://www.twse.com.tw/exchangeReport/TWTAUU"
              if kind == "CAPITAL_REDUCTION" else
              "https://www.twse.com.tw/rwd/zh/exRight/TWT49U")
    return {
        "market": market, "stock_id": stock_id, "ex_date": ex_date,
        "action_type_candidate": kind,
        "reference_price_factor_if_available": 0.975,
        "explicit_cash_dividend_per_share": cash,
        "share_exchange_per_thousand_if_available": None,
        "official_source": source,
        "source_raw_record_sha256": "a" * 64,
        "issuer_original_announcement_time_verified": False,
        "historical_total_return_adjustment_verified": False,
    }


def all_evidence(*, inject=True):
    d, f, e, r = fake_study()
    _, _, periods = validate_study(d, f, e, r)
    monthly = [fake_month(s, t, [fake_candidate()] if inject and s.month == 11 else [])
               for s, t in periods]
    return d, f, e, r, monthly


class OfficialActionReconcileTests(unittest.TestCase):
    def test_four_months_official_event_inside_holding_is_review_not_alpha(self):
        d, f, e, ready, months = all_evidence()
        result = reconcile(dataset=d, fixed=f, expanding=e, readiness=ready, reports=months)
        self.assertEqual(result["official_preview_periods_structurally_present"], 4)
        self.assertEqual(result["twse_research_cohort_candidate_events"], 1)
        self.assertEqual(result["research_windows_with_event_candidate"], 1)
        self.assertEqual(result["window_candidate_overlap"][9]["stocks_with_candidates"], ["2308"])
        self.assertFalse(result["true_total_return_label_verified"])
        self.assertTrue(result["no_preview_event_does_not_prove_no_actual_action"])
        self.assertEqual(result["database_connections"], 0)
        self.assertEqual(result["database_writes"], 0)
        self.assertEqual(result["line_messages_sent"], 0)
        self.assertEqual(result["release_decision"], "BLOCKED")

    def test_zero_preview_events_never_certifies_no_dividends(self):
        d, f, e, ready, months = all_evidence(inject=False)
        result = reconcile(dataset=d, fixed=f, expanding=e, readiness=ready, reports=months)
        self.assertEqual(result["twse_research_cohort_candidate_events"], 0)
        self.assertFalse(result["true_total_return_label_verified"])
        self.assertTrue(result["monthly_source_files_not_independently_authenticated"])

    def test_missing_or_misaligned_months_fail_closed(self):
        d, f, e, ready, months = all_evidence()
        for reports in (months[:-1], months[::-1], months + months[-1:]):
            with self.assertRaises(ValueError):
                reconcile(dataset=d, fixed=f, expanding=e, readiness=ready, reports=reports)

    def test_missing_fourth_source_or_wrong_source_url_rejected(self):
        d, f, e, ready, months = all_evidence()
        p = deepcopy(months[-1]); p["source_evidence"].pop()
        with self.assertRaises(ValueError):
            inspect_month(p, date(2026, 11, 1), date(2026, 11, 14))
        p = deepcopy(months[-1]); p["source_evidence"][0]["source"] = "https://fake.invalid/"
        with self.assertRaises(ValueError):
            inspect_month(p, date(2026, 11, 1), date(2026, 11, 14))

    def test_source_counts_and_dedup_must_reconcile(self):
        d, f, e, ready, months = all_evidence()
        p = deepcopy(months[-1]); p["raw_four_digit_source_events"] = 9
        with self.assertRaises(ValueError):
            inspect_month(p, date(2026, 11, 1), date(2026, 11, 14))
        p = deepcopy(months[-1]); p["candidates"].append(p["candidates"][0])
        p["distinct_candidate_economic_events"] = 2
        p["raw_four_digit_source_events"] = 2
        p["source_evidence"][0]["received_rows"] += 1
        p["source_evidence"][0]["four_digit_candidates"] += 1
        with self.assertRaises(ValueError):
            inspect_month(p, date(2026, 11, 1), date(2026, 11, 14))

    def test_unknown_or_excluded_stock_not_in_study(self):
        d, f, e, ready, months = all_evidence()
        d["frozen_current_stock_roster"][0] = "1589"
        with self.assertRaises(ValueError):
            validate_study(d, f, e, ready)
        d, f, e, ready, months = all_evidence()
        extra = fake_candidate(stock_id="1589")
        months[-1]["candidates"].append(extra)
        months[-1]["distinct_candidate_economic_events"] += 1
        months[-1]["raw_four_digit_source_events"] += 1
        months[-1]["source_evidence"][0]["received_rows"] += 1
        months[-1]["source_evidence"][0]["four_digit_candidates"] += 1
        result = reconcile(dataset=d, fixed=f, expanding=e, readiness=ready, reports=months)
        self.assertEqual(result["twse_research_cohort_candidate_events"], 1)
        self.assertEqual({c["stock_id"] for c in result["candidate_events"]}, {"2308"})

    def test_same_day_entry_is_cautiously_flagged_not_claimed_entitled(self):
        d, f, e, ready, months = all_evidence()
        months[-1]["candidates"][0]["ex_date"] = "2026-11-09"
        result = reconcile(dataset=d, fixed=f, expanding=e, readiness=ready, reports=months)
        self.assertEqual(result["window_candidate_overlap"][9][
            "candidate_on_entry_day_possible_no_dividend_entitlement"], 1)

    def test_tampered_dataset_or_unblocked_release_fails(self):
        d, f, e, ready, months = all_evidence()
        d["rows"][0]["stock_id"] = "1589"
        with self.assertRaises(ValueError):
            reconcile(dataset=d, fixed=f, expanding=e, readiness=ready, reports=months)
        d, f, e, ready, months = all_evidence()
        ready["release_decision"] = "APPROVED"
        with self.assertRaises(ValueError):
            reconcile(dataset=d, fixed=f, expanding=e, readiness=ready, reports=months)
        d, f, e, ready, months = all_evidence()
        e["nonoverlap_windows"][0]["last_mature_training_exit"] = e["nonoverlap_windows"][0]["signal_date"]
        with self.assertRaises(ValueError):
            reconcile(dataset=d, fixed=f, expanding=e, readiness=ready, reports=months)

    def test_fake_source_time_and_false_adjustment_claim_rejected(self):
        d, f, e, ready, months = all_evidence()
        p = deepcopy(months[-1]); p["first_seen_at_utc"] = "2026-10-01T00:00:00Z"
        with self.assertRaises(ValueError):
            inspect_month(p, date(2026, 11, 1), date(2026, 11, 14))
        p = deepcopy(months[-1]); p["verified_total_return_labels"] = True
        with self.assertRaises(ValueError):
            inspect_month(p, date(2026, 11, 1), date(2026, 11, 14))
        p = deepcopy(months[-1]); p["candidates"][0]["historical_total_return_adjustment_verified"] = True
        with self.assertRaises(ValueError):
            inspect_month(p, date(2026, 11, 1), date(2026, 11, 14))

    def test_invalid_cash_and_price_factor_are_blocked(self):
        d, f, e, ready, months = all_evidence()
        p = deepcopy(months[-1]); p["candidates"][0]["explicit_cash_dividend_per_share"] = float("nan")
        with self.assertRaises(ValueError):
            inspect_month(p, date(2026, 11, 1), date(2026, 11, 14))
        p = deepcopy(months[-1]); p["candidates"][0]["reference_price_factor_if_available"] = -1
        with self.assertRaises(ValueError):
            inspect_month(p, date(2026, 11, 1), date(2026, 11, 14))

    def test_corporate_action_kind_must_match_exact_market_feed(self):
        d, f, e, ready, months = all_evidence()
        p = deepcopy(months[-1])
        p["candidates"][0]["official_source"] = "https://www.twse.com.tw/exchangeReport/TWTAUU"
        with self.assertRaises(ValueError):
            inspect_month(p, date(2026, 11, 1), date(2026, 11, 14))

    def test_month_bounds_no_gaps(self):
        v = month_windows(date(2026, 8, 11), date(2026, 11, 20))
        self.assertEqual([(a.isoformat(), b.isoformat()) for a, b in v], [
            ("2026-08-01", "2026-08-31"), ("2026-09-01", "2026-09-30"),
            ("2026-10-01", "2026-10-31"), ("2026-11-01", "2026-11-20")])


if __name__ == "__main__":
    unittest.main()
