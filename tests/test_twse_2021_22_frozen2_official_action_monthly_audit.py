"""Synthetic historical TWSE issuer-event response tests: no private files or URL."""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock

from scripts.twse_2022_known_cash_events_sma240_readonly import SCOPE as PRIOR_SCOPE
from scripts.twse_2021_22_frozen2_official_action_monthly_audit import (
    EXPECTED_KNOWN_EVENTS, MAX_MONTHS, SCOPE, SOURCES,
    assess_monthly_history, fetch_month_kind, months_and_bounds,
    parse_month_response, validate_owner_prior,
)


def prior():
    return {
        "schema_version": 1, "scope": PRIOR_SCOPE,
        "research_asof_session": "2022-12-30",
        "live_model_release_decision": "BLOCKED",
        "two_known_cash_events_sma240_stock_count": 2,
        "dated_dividend_events_included": 2,
        "dated_capital_reduction_events_included": 2,
        "genuine_halt_market_days_no_fake_bars": 14,
        "corporate_actions_master_complete": False,
        "historical_listing_membership_or_capture_vintage_certified": False,
        "total_return_cash_payment_or_reinvestment_certified": False,
        "neon_writes": 0,
        "line_messages_sent": 0,
        "per_stock_two_known_event_research_proofs": [
            {
                "stock_id": stock,
                "genuine_source_stock_trading_days": 240,
                "last240_first_stock_trade": "2021-12-30",
                "last240_last_stock_trade": "2022-12-30",
                "only_two_previously_verified_cash_events_applied": True,
                "full_dividend_split_action_ledger_proven": False,
                "full_model_release_approved": False,
            }
            for stock in ("2327", "2603")
        ],
    }


def row(stock, year, month, day, label="息", *, kind="ex"):
    if kind == "ex":
        return {
            "證券代號": stock, "除權息日期": f"{year-1911}/{month:02d}/{day:02d}",
            "權或息": label, "除權息前收盤價": "100.00",
            "除權息參考價": "90.00",
        }
    return {
        "股票代號": stock, "恢復買賣日期": f"{year-1911}/{month:02d}/{day:02d}",
        "停止買賣前收盤價": "100.00",
        "恢復買賣參考價": "125.00",
    }


def synthetic_fetcher(kind, start, end):
    rows = []
    for stock, d, category in EXPECTED_KNOWN_EVENTS:
        if start <= d <= end:
            if category == "CAPITAL_REDUCTION" and kind == "reduction":
                rows.append(row(stock, d.year, d.month, d.day, kind="reduction"))
            if category == "CASH_DIVIDEND" and kind == "ex":
                rows.append(row(stock, d.year, d.month, d.day))
    # A real unrelated 4-digit issuer in same requested month is allowed but
    # must never make it into the two-stock output.
    if kind == "ex":
        rows.append(row("1589", start.year, start.month, start.day))
    parsed = parse_month_response(
        {"stat": "OK", "data": rows},
        kind=kind, begin=start, end=end)
    return dict(parsed, response_sha256="a"*64, source_url=SOURCES[kind],
                requested_start=start.isoformat(),
                requested_end=end.isoformat())


class HistoricalTWSEOfficialActionsOfflineTests(unittest.TestCase):
    def test_month_interval_bounded_to_exact_240_window(self):
        m = months_and_bounds("2021-12", "2022-12")
        self.assertEqual(len(m), MAX_MONTHS)
        self.assertEqual(m[0], ("2021-12", date(2021, 12, 30),
                                date(2021, 12, 31)))
        self.assertEqual(m[-1], ("2022-12", date(2022, 12, 1),
                                 date(2022, 12, 30)))
        for first, last in (
            ("2021-11", "2022-12"), ("2022-10", "2022-08"),
            ("2022-12", "2023-01"), ("2022-00", "2022-01"),
            ("2021-12-01", "2022-12"),
        ):
            with self.assertRaises(ValueError):
                months_and_bounds(first, last)

    def test_all_13_requested_months_26_responses_four_known_events(self):
        result = assess_monthly_history(
            prior(), start_month="2021-12", end_month="2022-12",
            fetcher=synthetic_fetcher)
        self.assertEqual(result["scope"], SCOPE)
        self.assertEqual(result["requested_month_count"], 13)
        self.assertEqual(result["requested_official_http_source_calls"], 26)
        self.assertTrue(result["all_13_calendar_months_queried"])
        self.assertEqual(result["known_previous_events_expected_in_window"], 4)
        self.assertEqual(result["known_previous_events_found_matching_source"], 4)
        self.assertTrue(result["all_known_previous_events_matched"])
        self.assertEqual(len(result["official_two_stock_events_observed"]), 4)
        self.assertEqual(result["production_neon_writes"], 0)
        self.assertEqual(result["line_messages_sent"], 0)
        self.assertEqual(result["model_release"], "BLOCKED")
        self.assertFalse(result["historical_api_coverage_independently_proven_exhaustive"])
        self.assertFalse(result["other_historical_issuer_dividends_and_splits_all_verified"])
        self.assertFalse(result["full_price_adjustment_or_total_return_approved"])
        self.assertFalse(result["empty_official_query_may_be_treated_as_zero_issuer_actions"])
        self.assertNotIn("adjusted_close", str(result))
        self.assertNotIn("original_close", str(result))

    def test_single_or_partial_month_does_not_claim_whole_period(self):
        result = assess_monthly_history(
            prior(), start_month="2022-06", end_month="2022-07",
            fetcher=synthetic_fetcher)
        self.assertEqual(result["requested_month_count"], 2)
        self.assertEqual(result["known_previous_events_expected_in_window"], 2)
        self.assertEqual(result["known_previous_events_found_matching_source"], 2)
        self.assertFalse(result["all_13_calendar_months_queried"])
        self.assertFalse(result["historical_api_coverage_independently_proven_exhaustive"])

    def test_known_cash_event_missing_is_visible_never_greenwashed(self):
        def absent_ex(kind, begin, end):
            r = synthetic_fetcher(kind, begin, end)
            if kind == "ex" and begin.month == 7:
                r["events"] = []
                r["received_rows"] = 0
                r["source_status"] = "NO_MATCH_NOT_EVIDENCE_OF_ZERO_ACTIONS"
            return r
        result = assess_monthly_history(
            prior(), start_month="2022-06", end_month="2022-10",
            fetcher=absent_ex)
        self.assertEqual(result["known_previous_events_expected_in_window"], 4)
        self.assertEqual(result["known_previous_events_found_matching_source"], 3)
        self.assertFalse(result["all_known_previous_events_matched"])
        self.assertEqual(result["known_previous_event_mismatches"], [
            {"stock_id": "2327", "date": "2022-07-04",
             "kind": "CASH_DIVIDEND"}
        ])
        self.assertFalse(result["full_price_adjustment_or_total_return_approved"])

    def test_list_of_list_json_fields_are_accepted_from_twse(self):
        r = parse_month_response(
            {"stat": "OK",
             "fields": ["除權息日期", "證券代號", "權或息", "除權息前收盤價"],
             "data": [["111/07/04", "2327", "息", "282"]]},
            kind="ex", begin=date(2022, 7, 1), end=date(2022, 7, 31))
        self.assertEqual(len(r["events"]), 1)
        self.assertEqual(r["events"][0]["stock_id"], "2327")
        self.assertEqual(r["events"][0]["reported_event_category"], "CASH_DIVIDEND")
        self.assertEqual(len(r["events"][0]["original_official_row_sha256"]), 64)

    def test_known_empty_does_not_prove_issuer_had_no_cash_payout(self):
        for payload in (
            {"stat": "OK", "data": []},
            {"stat": "很抱歉，沒有符合條件的資料", "data": []},
        ):
            x = parse_month_response(
                payload, kind="ex",
                begin=date(2022, 3, 1), end=date(2022, 3, 31))
            self.assertEqual(x["received_rows"], 0)
            self.assertIn(x["source_status"], (
                "OK_EMPTY_NOT_ZERO_PROOF",
                "NO_MATCH_NOT_EVIDENCE_OF_ZERO_ACTIONS",
            ))
            self.assertEqual(x["events"], [])

    def test_ignored_historical_query_rejected_even_if_not_target_stock(self):
        for stock in ("2327", "9999", "1589"):
            with self.assertRaisesRegex(ValueError, "ignored requested"):
                parse_month_response(
                    {"stat": "OK", "data": [row(stock, 2026, 11, 23)]},
                    kind="ex", begin=date(2022, 6, 1),
                    end=date(2022, 6, 30))

    def test_bogus_source_status_invalid_dates_and_duplicate_event_refused(self):
        x = row("2327", 2022, 7, 4)
        for payload in (
            {"stat": "BAD_GATEWAY", "data": []},
            {"data": [x]},
            {"stat": "OK", "data": [x, dict(x)]},
            {"stat": "OK", "data": [dict(x, 除權息日期="111/07/33")]},
        ):
            with self.assertRaises(ValueError):
                parse_month_response(
                    payload, kind="ex",
                    begin=date(2022, 7, 1), end=date(2022, 7, 31))

    def test_split_or_mixed_event_not_silently_cash_dividend(self):
        x = parse_month_response(
            {"stat": "OK", "data": [
                row("2327", 2022, 8, 2, "權"),
                row("2603", 2022, 8, 3, "權息"),
            ]}, kind="ex", begin=date(2022, 8, 1),
            end=date(2022, 8, 31))
        self.assertEqual([event["reported_event_category"] for event in
                          x["events"]],
                         ["STOCK_DIVIDEND", "COMBINED_OR_UNCLASSIFIED"])

    def test_unverified_owner_previous_report_fails_before_any_network(self):
        for key, value in (
            ("scope", "INVALID"), ("model_release", "APPROVED"),
            ("live_model_release_decision", "APPROVED"), ("neon_writes", 1),
            ("corporate_actions_master_complete", True),
        ):
            base = prior()
            base[key] = value
            if key == "model_release":
                continue
            called = []
            with self.assertRaises(ValueError):
                assess_monthly_history(
                    base, start_month="2022-06", end_month="2022-07",
                    fetcher=lambda *args: called.append(args))
            self.assertEqual(called, [])

    def test_response_receipt_cannot_be_faked_or_misdated(self):
        def bad(kind, begin, end):
            s = synthetic_fetcher(kind, begin, end)
            s["response_sha256"] = "bad"
            return s
        with self.assertRaises(ValueError):
            assess_monthly_history(
                prior(), start_month="2022-06", end_month="2022-07",
                fetcher=bad)
        def wrong_month(kind, begin, end):
            s = synthetic_fetcher(kind, begin, end)
            s["requested_start"] = "2026-11-23"
            return s
        with self.assertRaises(ValueError):
            assess_monthly_history(
                prior(), start_month="2022-06", end_month="2022-07",
                fetcher=wrong_month)

    def test_get_uses_only_official_https_with_strict_params_and_fingerprint(self):
        content = json.dumps({"stat": "OK", "data": [
            row("2327", 2022, 7, 4)]}, ensure_ascii=False).encode()
        response = Mock()
        response.content = content
        response.url = SOURCES["ex"]
        response.json.return_value = json.loads(content)
        getter = Mock(return_value=response)
        result = fetch_month_kind(
            "ex", date(2022, 7, 1), date(2022, 7, 31), get=getter)
        self.assertEqual(result["response_sha256"], sha256(content).hexdigest())
        args, kwargs = getter.call_args
        self.assertEqual(args[0], SOURCES["ex"])
        self.assertEqual(kwargs["params"]["startDate"], "20220701")
        self.assertEqual(kwargs["params"]["endDate"], "20220731")
        self.assertIn("timeout", kwargs)
        response.url = "https://unverified.example.org/redirect"
        with self.assertRaises(ValueError):
            fetch_month_kind(
                "ex", date(2022, 7, 1), date(2022, 7, 31), get=getter)

    def test_cli_help_no_neon_or_owner_aes(self):
        root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        for key in ("DATABASE_URL", "STOCK_ARCHIVE_KEY_HEX", "PYTHONPATH"):
            env.pop(key, None)
        result = subprocess.run(
            [sys.executable, "-m",
             "scripts.twse_2021_22_frozen2_official_action_monthly_audit",
             "--help"],
            cwd=root, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--month-start", result.stdout)
        self.assertIn("--prior-report", result.stdout)


if __name__ == "__main__":
    unittest.main()
