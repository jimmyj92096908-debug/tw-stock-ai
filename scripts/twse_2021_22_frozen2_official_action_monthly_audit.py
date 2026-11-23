"""Owner-only historical TWSE issuer-event response inventory; no database access.

Bounded 2021-12-30..2022-12-30, currently-listed 2327 and 2603 only.
Queries *free* official TWSE historical ex-right/ex-dividend (TWT49U) and
capital-reduction resumption (TWTAUU) results by individual calendar month.
Requires owner prior #227 accepted report. Records response fingerprints and
event categories/dates, not raw response, prices, amount/factor or credentials.

IMPORTANT: A successful query, a "no rows" response, or a match to all
four known events DOES NOT prove an exhaustive company-action/total-return
ledger, original-issuer publication vintage, or PIT completeness.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import urlparse

from scripts.twse_2021_22_traded_240_warmup_readonly import _private_file
from scripts.twse_2022_known_cash_events_sma240_readonly import SCOPE as PRIOR_SCOPE
from scripts.official_dividend_monthly_preview import _parse_official_event_date
from src.corporate_actions_data import (
    TWSE_EX_URL, TWSE_REDUCTION_URL, _pick, unpack,
)

SCOPE = "OWNER_2021_22_TWSE_FROZEN2_HISTORICAL_OFFICIAL_ACTION_RESPONSES"
TARGETS = frozenset(("2327", "2603"))
AUDITED_ALTERNATE_TARGETS = frozenset(("1101", "2330"))
ALLOWED_READONLY_TARGETS = TARGETS | AUDITED_ALTERNATE_TARGETS
QUERY_START = date(2021, 12, 30)
QUERY_END = date(2022, 12, 30)
MAX_MONTHS = 13
MAX_BYTES_PER_RESPONSE = 3_000_000
MAX_ROWS_PER_RESPONSE = 4_000
SOURCES = {"ex": TWSE_EX_URL, "reduction": TWSE_REDUCTION_URL}
EXPECTED_KNOWN_EVENTS = frozenset({
    ("2327", date(2022, 7, 4), "CASH_DIVIDEND"),
    ("2603", date(2022, 6, 29), "CASH_DIVIDEND"),
    ("2327", date(2022, 10, 31), "CAPITAL_REDUCTION"),
    ("2603", date(2022, 9, 19), "CAPITAL_REDUCTION"),
})


def months_and_bounds(first: str, last: str):
    if (not isinstance(first, str) or not isinstance(last, str)
            or not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", first)
            or not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", last)
            or not "2021-12" <= first <= last <= "2022-12"):
        raise ValueError("Only 2021-12 through 2022-12 valid ordered months")
    y, m = map(int, first.split("-"))
    ey, em = map(int, last.split("-"))
    parts = []
    while (y, m) <= (ey, em):
        begin = max(date(y, m, 1), QUERY_START)
        if m == 12:
            end = min(date(y, 12, 31), QUERY_END)
        else:
            end = min(date(y, m + 1, 1).fromordinal(
                date(y, m + 1, 1).toordinal() - 1), QUERY_END)
        if begin <= end:
            parts.append((f"{y:04d}-{m:02d}", begin, end))
        if len(parts) > MAX_MONTHS:
            raise ValueError("Monthly official request budget exceeded")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    if not parts:
        raise ValueError("No allowed historical calendar days")
    return parts


def validate_owner_prior(report):
    if (not isinstance(report, dict)
            or report.get("schema_version") != 1
            or report.get("scope") != PRIOR_SCOPE
            or report.get("research_asof_session") != QUERY_END.isoformat()
            or report.get("live_model_release_decision") != "BLOCKED"
            or report.get("two_known_cash_events_sma240_stock_count") != 2
            or report.get("dated_dividend_events_included") != 2
            or report.get("dated_capital_reduction_events_included") != 2
            or report.get("genuine_halt_market_days_no_fake_bars") != 14
            or report.get("corporate_actions_master_complete") is not False
            or report.get("historical_listing_membership_or_capture_vintage_certified") is not False
            or report.get("total_return_cash_payment_or_reinvestment_certified") is not False
            or report.get("neon_writes") != 0
            or report.get("line_messages_sent") != 0):
        raise ValueError("Not the owner-accepted blocked two-stock #227 proof")
    witnesses = report.get("per_stock_two_known_event_research_proofs")
    if not isinstance(witnesses, list) or len(witnesses) != 2:
        raise ValueError("Missing prior 240 real-traded-day per-stock witnesses")
    seen = set()
    for witness in witnesses:
        if (not isinstance(witness, dict)
                or witness.get("stock_id") not in TARGETS
                or witness["stock_id"] in seen
                or witness.get("genuine_source_stock_trading_days") != 240
                or witness.get("last240_first_stock_trade") != "2021-12-30"
                or witness.get("last240_last_stock_trade") != QUERY_END.isoformat()
                or witness.get("only_two_previously_verified_cash_events_applied") is not True
                or witness.get("full_dividend_split_action_ledger_proven") is not False
                or witness.get("full_model_release_approved") is not False):
            raise ValueError("Prior research witness missing or altered")
        seen.add(witness["stock_id"])
    if seen != TARGETS:
        raise ValueError("Wrong frozen issuer study cohort")


def parse_month_response(payload: dict, *, kind: str, begin: date, end: date,
                         targets=TARGETS):
    """Pure validator, rejects out-of-period rows including other issuers."""
    if (kind not in SOURCES or not isinstance(payload, dict)
            or type(targets) is not frozenset or not targets
            or not targets.issubset(ALLOWED_READONLY_TARGETS)
            or type(begin) is not date or type(end) is not date
            or not QUERY_START <= begin <= end <= QUERY_END):
        raise ValueError("Invalid official historical month request")
    stat = payload.get("stat")
    if not isinstance(stat, str) or len(stat) > 150:
        raise ValueError("Official historical feed did not return explicit status")
    if stat.strip().upper() != "OK":
        if (any(text in stat for text in ("沒有符合", "沒有資料", "查無", "無符合", "很抱歉"))
                or "NO DATA" in stat.upper()):
            return {"source_status": "NO_MATCH_NOT_EVIDENCE_OF_ZERO_ACTIONS",
                    "received_rows": 0, "events": []}
        raise ValueError("TWSE source did not report successful historical query")
    if isinstance(payload.get("data"), list) and not payload["data"]:
        rows = []
    elif isinstance(payload.get("tables"), list) and not payload["tables"]:
        rows = []
    else:
        rows = unpack(payload)
    if len(rows) > MAX_ROWS_PER_RESPONSE:
        raise ValueError("Official historical result too large to audit safely")
    matches = []
    keys = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("TWSE result event record is not a JSON object")
        sid = str(_pick(row, [
            "股票代號", "證券代號", "代號", "Code", "SecuritiesCompanyCode",
        ]) or "").strip()
        if not re.fullmatch(r"\d{4}", sid):
            continue
        date_field = (["除權息日期", "除權日期", "資料日期", "日期", "Date"]
                      if kind == "ex" else
                      ["恢復買賣日期", "恢復交易日期", "資料日期", "日期", "Date"])
        raw_date = _pick(row, date_field)
        if raw_date is None:
            raise ValueError("Four-digit listed security event missing real date")
        d = _parse_official_event_date(
            raw_date, market="twse", kind=kind, symbol=sid)
        if not begin <= d <= end:
            raise ValueError("Official endpoint ignored requested historical dates")
        if sid not in targets:
            continue
        if kind == "reduction":
            category = "CAPITAL_REDUCTION"
        else:
            label = str(_pick(row, [
                "權/息", "權或息", "除權息", "類別", "權息別",
            ]) or "")
            if "息" in label and "權" not in label:
                category = "CASH_DIVIDEND"
            elif "權" in label and "息" not in label:
                category = "STOCK_DIVIDEND"
            else:
                category = "COMBINED_OR_UNCLASSIFIED"
        digest = sha256(json.dumps(
            row, sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), default=str).encode()).hexdigest()
        key = (sid, d, category)
        if key in keys:
            raise ValueError("Duplicate/conflicting official event type on same date")
        keys.add(key)
        matches.append({
            "stock_id": sid,
            "event_date": d.isoformat(),
            "reported_event_category": category,
            "original_official_row_sha256": digest,
            "original_issuer_announcement_timestamp_available": False,
            "historical_cash_entitlement_or_share_factor_certified": False,
        })
    return {
        "source_status": "OK_WITH_ROWS" if rows else "OK_EMPTY_NOT_ZERO_PROOF",
        "received_rows": len(rows),
        "events": sorted(matches, key=lambda a: (
            a["event_date"], a["stock_id"], a["reported_event_category"])),
    }


def fetch_month_kind(kind, begin, end, *, get=None, targets=TARGETS):
    """Actual HTTP requests stay entirely on public TWSE, never Neon."""
    if kind not in SOURCES:
        raise ValueError("Unrecognized exchange endpoint")
    if get is None:
        import requests
        get = requests.get
    params = {
        "startDate": begin.strftime("%Y%m%d"),
        "endDate": end.strftime("%Y%m%d"),
        "response": "json",
    }
    url = SOURCES[kind]
    if urlparse(url).hostname != "www.twse.com.tw":
        raise ValueError("Only official TWSE HTTPS origin permitted")
    response = get(
        url, params=params, timeout=(8, 25),
        headers={"Accept": "application/json",
                 "User-Agent": "tw-stock-ai-free-historical-action-audit"})
    response.raise_for_status()
    if urlparse(response.url).hostname != "www.twse.com.tw":
        raise ValueError("Official HTTP request redirected to unapproved host")
    data = response.content
    if not isinstance(data, bytes) or len(data) > MAX_BYTES_PER_RESPONSE:
        raise ValueError("TWSE response exceeds audited no-cost size cap")
    payload = response.json()
    report = parse_month_response(
        payload, kind=kind, begin=begin, end=end, targets=targets)
    report["response_sha256"] = sha256(data).hexdigest()
    report["source_url"] = url
    report["requested_start"] = begin.isoformat()
    report["requested_end"] = end.isoformat()
    return report


def assess_monthly_history(prior, *, start_month, end_month, fetcher):
    validate_owner_prior(prior)
    months = months_and_bounds(start_month, end_month)
    timeline = []
    observed_events = []
    kinds = set()
    verified_month_pair_count = 0
    for month, begin, end in months:
        for kind in ("ex", "reduction"):
            result = fetcher(kind, begin, end)
            if not isinstance(result, dict) or result.get(
                    "source_status") not in (
                        "OK_WITH_ROWS", "OK_EMPTY_NOT_ZERO_PROOF",
                        "NO_MATCH_NOT_EVIDENCE_OF_ZERO_ACTIONS"):
                raise ValueError("Official month response never actually accepted")
            observed = result.get("events")
            n = result.get("received_rows")
            if (not isinstance(observed, list) or type(n) is not int
                    or n < len(observed) or n > MAX_ROWS_PER_RESPONSE
                    or not isinstance(result.get("response_sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}",
                                        result["response_sha256"])
                    or result.get("source_url") != SOURCES[kind]
                    or result.get("requested_start") != begin.isoformat()
                    or result.get("requested_end") != end.isoformat()):
                raise ValueError("Unverified or tampered monthly official source response")
            for item in observed:
                if not isinstance(item, dict):
                    raise ValueError("Malformed verified month event record")
                sid = item.get("stock_id")
                event_day = date.fromisoformat(item["event_date"])
                category = item.get("reported_event_category")
                if (sid not in TARGETS or not begin <= event_day <= end
                        or category not in (
                            "CASH_DIVIDEND", "STOCK_DIVIDEND",
                            "COMBINED_OR_UNCLASSIFIED", "CAPITAL_REDUCTION")
                        or (kind == "reduction") != (
                            category == "CAPITAL_REDUCTION")
                        or item.get("original_issuer_announcement_timestamp_available") is not False
                        or item.get("historical_cash_entitlement_or_share_factor_certified") is not False
                        or not re.fullmatch(r"[0-9a-f]{64}", item.get(
                            "original_official_row_sha256", ""))):
                    raise ValueError("Invalid event provenance or month boundary")
                key = (sid, event_day, category)
                if key in kinds:
                    raise ValueError("Duplicated official event across independent responses")
                kinds.add(key)
                observed_events.append(item)
            if result["source_status"] == "OK_WITH_ROWS":
                verified_month_pair_count += 1
            timeline.append({
                "month": month,
                "kind": kind,
                "source_url": SOURCES[kind],
                "original_response_sha256": result["response_sha256"],
                "request_day_from": begin.isoformat(),
                "request_day_to": end.isoformat(),
                "http_json_status_class": result["source_status"],
                "public_all_issuer_rows_returned": n,
                "frozen_two_stock_event_rows_found": len(observed),
                "empty_response_is_not_proof_of_zero_events": True,
            })
    expected = {
        event for event in EXPECTED_KNOWN_EVENTS
        if months[0][1] <= event[1] <= months[-1][2]
    }
    seen = {
        (item["stock_id"], date.fromisoformat(item["event_date"]),
         item["reported_event_category"])
        for item in observed_events
    }
    missing = sorted(expected - seen)
    all_months = (start_month == "2021-12" and end_month == "2022-12")
    return {
        "schema_version": 1,
        "scope": SCOPE,
        "requested_month_count": len(months),
        "requested_official_http_source_calls": len(timeline),
        "source_date_from": months[0][1].isoformat(),
        "source_date_through": months[-1][2].isoformat(),
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "monthly_source_response_receipts": timeline,
        "official_two_stock_events_observed": sorted(
            observed_events, key=lambda r: (
                r["event_date"], r["stock_id"], r["reported_event_category"])),
        "known_previous_events_expected_in_window": len(expected),
        "known_previous_events_found_matching_source": len(expected) - len(missing),
        "known_previous_event_mismatches": [
            {"stock_id": sid, "date": day.isoformat(), "kind": kind}
            for sid, day, kind in missing],
        "all_known_previous_events_matched": not missing,
        "all_13_calendar_months_queried": all_months,
        "source_responses_with_nonempty_public_rows": verified_month_pair_count,
        "historical_api_coverage_independently_proven_exhaustive": False,
        "empty_official_query_may_be_treated_as_zero_issuer_actions": False,
        "other_historical_issuer_dividends_and_splits_all_verified": False,
        "historical_issuer_publication_vintage_verified": False,
        "full_price_adjustment_or_total_return_approved": False,
        "last240_two_stock_original_private_study_still_240_each": True,
        "production_neon_writes": 0,
        "line_messages_sent": 0,
        "paid_sources_used": False,
        "model_release": "BLOCKED",
    }


def main():
    parser = argparse.ArgumentParser(
        description="Official TWSE monthly 2021-22 two-stock event inventory, NO DB")
    parser.add_argument("--month-start", default="2021-12")
    parser.add_argument("--month-end", default="2022-12")
    parser.add_argument("--prior-report", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        prior_file = _private_file(args.prior_report, should_exist=True)
        new_file = _private_file(args.out, should_exist=False)
        if prior_file == new_file:
            raise ValueError("Cannot overwrite prior owner report")
        prior = json.loads(prior_file.read_text(encoding="utf-8"))
        result = assess_monthly_history(
            prior, start_month=args.month_start, end_month=args.month_end,
            fetcher=fetch_month_kind)
        with new_file.open("x", encoding="utf-8") as fp:
            json.dump(result, fp, ensure_ascii=False, indent=2, allow_nan=False)
            fp.write("\n")
        print(json.dumps({
            "status": "TWSE_2021_22_HISTORICAL_EVENT_RESPONSE_AUDIT_PASS",
            "requested_months": result["requested_month_count"],
            "official_response_calls": result["requested_official_http_source_calls"],
            "two_stock_event_candidates": len(
                result["official_two_stock_events_observed"]),
            "known_events_found": result[
                "known_previous_events_found_matching_source"],
            "known_events_expected": result[
                "known_previous_events_expected_in_window"],
            "all_known_events_matched": result[
                "all_known_previous_events_matched"],
            "historical_event_universe_complete": False,
            "neon_writes": 0,
            "line_messages_sent": 0,
            "model_release": "BLOCKED",
        }, ensure_ascii=False))
    except Exception:
        raise SystemExit(
            "Historical TWSE issuer-event monthly source audit FAILED; "
            "no Neon writes, LINE messages, private source or credentials printed"
        ) from None


if __name__ == "__main__":
    main()
