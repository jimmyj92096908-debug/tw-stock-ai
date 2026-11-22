"""Read-only 2327/2603 2021-22 *recorded* corporate-action coverage blocker.

A single 2022 cash-reduction-only SMA240 does NOT establish dividend,
split, total-return, publication-vintage, or historic completeness. Only
reads existing corporate_actions for 2327 and 2603 within the *exact*
240-traded-day window proven by an owner-private prior report.

No source fetch, INSERT/UPDATE/DELETE, archive edits, factor recomputation,
model deployment, or LINE messages. Counts are NOT proof of completeness.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re

from scripts.twse_2021_22_traded_240_warmup_readonly import _private_file
from scripts.twse_2022_reduction_only_240_sma_readonly import SMA_SCOPE

STOCKS = ("2327", "2603")
START = date(2021, 12, 30)
END = date(2022, 12, 30)
MAX_ROWS = 200
EVIDENCE_SCOPE = "OWNER_ONLY_2022_TWSE_FROZEN2_CORPORATE_ACTION_COVERAGE_AUDIT"
REDUCTION_TYPES = frozenset({
    "CASH_CAPITAL_REDUCTION", "CASH_REDUCTION",
    "CAPITAL_REDUCTION", "CAPITAL_REDUCTION_CASH",
})
SQL_COUNT = """
SELECT COUNT(*)::int AS n
FROM public.corporate_actions
WHERE market='twse'
  AND stock_id = ANY(%s::varchar[])
  AND ex_date >= %s AND ex_date <= %s
"""
SQL_ACTIONS = """
SELECT market,stock_id,ex_date,action_type,price_factor,share_factor,
       cash_amount,stock_amount,source_event_id,source,verified,created_at
FROM public.corporate_actions
WHERE market='twse'
  AND stock_id = ANY(%s::varchar[])
  AND ex_date >= %s AND ex_date <= %s
ORDER BY stock_id,ex_date,action_type,source_event_id
LIMIT %s
"""


def _number(value, *, strictly_positive=False):
    if value is None:
        if strictly_positive:
            raise ValueError("Missing required corporate-action factor")
        return None
    try:
        x = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Invalid corporate-action economic value") from exc
    if (not x.is_finite() or (strictly_positive and x <= 0)
            or (not strictly_positive and x < 0)):
        raise ValueError("Invalid corporate-action economic value")
    return str(x.normalize())


def validate_prior_sma_report(report):
    """Only real, already accepted, bounded 2022 event-only evidence."""
    if (not isinstance(report, dict)
            or report.get("schema_version") != 1
            or report.get("scope") != SMA_SCOPE
            or report.get("live_model_release_decision") != "BLOCKED"
            or report.get("event_only_240_sma_stock_count") != 2
            or report.get("production_neon_writes") != 0
            or report.get("line_messages_sent") != 0
            or report.get("complete_all_corporate_actions_adjusted") is not False
            or report.get("point_in_time_historical_listed_roster_proven") is not False
            or report.get("real_2022_capital_reduction_halt_days_left_without_price") != 14):
        raise ValueError("Prior owner evidence is not the blocked two-stock report")
    witnesses = report.get("stock_capital_reduction_only_research_witnesses")
    if not isinstance(witnesses, list) or len(witnesses) != 2:
        raise ValueError("Missing exact two-stock 240-traded-day witnesses")
    seen = set()
    for row in witnesses:
        if (not isinstance(row, dict)
                or row.get("stock_id") not in STOCKS
                or row["stock_id"] in seen
                or row.get("last240_first_real_stock_session") != START.isoformat()
                or row.get("last240_final_real_stock_session") != END.isoformat()
                or row.get("last240_real_traded_days") != 240
                or row.get("2022_cash_reduction_only_decimal_sma240_computed_in_ram") is not True
                or row.get("fully_adjusted_sma240_release_approved") is not False):
            raise ValueError("Not the accepted 2021/22 per-stock 240-day window")
        seen.add(row["stock_id"])
    if seen != set(STOCKS):
        raise ValueError("Unrecognized or missing stock in private evidence")


def assess_recorded_actions(prior, rows, *, total_rows):
    """Only summarize recorded database events; NEVER assert events absent."""
    validate_prior_sma_report(prior)
    if (type(total_rows) is not int or not 0 <= total_rows <= MAX_ROWS
            or not isinstance(rows, list) or len(rows) != total_rows):
        raise ValueError("Incomplete or truncated two-stock action inventory")
    counts = {sid: Counter() for sid in STOCKS}
    type_counts = {sid: Counter() for sid in STOCKS}
    observed_economics = {sid: set() for sid in STOCKS}
    seen_event_ids = set()
    distinct_type_day_economics = {}
    for e in rows:
        if not isinstance(e, dict):
            raise ValueError("Invalid corporate action record")
        sid, d = e.get("stock_id"), e.get("ex_date")
        action = e.get("action_type")
        event_id = e.get("source_event_id")
        source = e.get("source")
        verified = e.get("verified")
        observed = e.get("created_at")
        if (e.get("market") != "twse" or sid not in STOCKS
                or type(d) is not date or not START <= d <= END
                or not isinstance(action, str) or not action.strip()
                or not isinstance(source, str) or not source.strip()
                or not isinstance(event_id, str) or not event_id.strip()
                or type(verified) is not bool):
            raise ValueError("Invalid corporate-action scope, provenance or date")
        key = (sid, d, event_id)
        if key in seen_event_ids:
            raise ValueError("Duplicated source event id on stock-date")
        seen_event_ids.add(key)
        pf = _number(e.get("price_factor"), strictly_positive=True)
        sf = _number(e.get("share_factor"), strictly_positive=True)
        cash = _number(e.get("cash_amount"))
        shares = _number(e.get("stock_amount"))
        economics = (d, action, pf, sf, cash, shares)
        observed_economics[sid].add(economics)
        distinct_type_day_economics.setdefault((sid, d, action), set()).add(
            (pf, sf, cash, shares))
        c = counts[sid]
        c["recorded_rows"] += 1
        if verified:
            c["verified_rows"] += 1
        else:
            c["unverified_rows"] += 1
        if action not in REDUCTION_TYPES:
            c["non_reduction_recorded_rows"] += 1
        if action == "CASH_DIVIDEND":
            c["cash_dividend_rows"] += 1
            if cash is None:
                c["cash_dividend_missing_amount_rows"] += 1
        if observed is None:
            c["missing_capture_timestamp_rows"] += 1
        elif not isinstance(observed, datetime) or observed.tzinfo is None:
            raise ValueError("Naive or malformed corporate-action capture time")
        elif observed.date() > d:
            c["first_captured_after_ex_date_rows"] += 1
        # Even a capture timestamp BEFORE ex-date cannot prove original
        # publication time; it is a DB observation, not an issuer notice.
        type_counts[sid][action] += 1

    report = []
    for sid in STOCKS:
        c = counts[sid]
        conflicts = sum(
            len(econ) > 1
            for (stock, _, _), econ in distinct_type_day_economics.items()
            if stock == sid
        )
        report.append({
            "stock_id": sid,
            "stored_event_rows_in_proven_240_traded_day_window": c["recorded_rows"],
            "distinct_stored_economic_events": len(observed_economics[sid]),
            "stored_verified_event_rows": c["verified_rows"],
            "stored_unverified_event_rows": c["unverified_rows"],
            "stored_non_cash_reduction_event_rows": c["non_reduction_recorded_rows"],
            "stored_cash_dividend_rows": c["cash_dividend_rows"],
            "stored_cash_dividend_rows_missing_amount":
                c["cash_dividend_missing_amount_rows"],
            "stored_events_first_captured_after_ex_date":
                c["first_captured_after_ex_date_rows"],
            "stored_events_without_capture_timestamp":
                c["missing_capture_timestamp_rows"],
            "same_stock_date_type_conflicting_economic_terms": conflicts,
            "stored_action_type_counts": dict(sorted(type_counts[sid].items())),
            "no_stored_event_means_no_real_dividend": False,
            "any_verified_stored_event_proves_complete_history": False,
            "source_capture_date_equals_original_issuer_publication_time": False,
            "full_corporate_action_and_dividend_history_verified": False,
            "adjusted_total_return_or_backtest_released": False,
        })
    return {
        "schema_version": 1,
        "scope": EVIDENCE_SCOPE,
        "original_evidence_scope": SMA_SCOPE,
        "actual_readonly_stored_action_rows": total_rows,
        "source_window_start": START.isoformat(),
        "source_window_end": END.isoformat(),
        "frozen_research_stock_count": 2,
        "per_stock_action_coverage": report,
        "independently_complete_historical_dividends_and_splits": False,
        "zero_stored_events_may_be_interpreted_as_no_dividends": False,
        "original_asof_issuer_publication_vintage_verified": False,
        "cash_reduction_only_sma240_is_complete_total_return": False,
        "recompute_or_persist_adjusted_prices": False,
        "validated_walkforward_total_return_labels": False,
        "production_neon_writes": 0,
        "line_messages_sent": 0,
        "paid_upgrade_requested": False,
        "live_model_release_decision": "BLOCKED",
    }


def read_existing_neon_actions():
    """Small SELECT-only transaction; no session options on pooled Neon URI."""
    import psycopg
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith(("postgresql://", "postgres://")):
        raise ValueError("Private read-only DATABASE_URL is required")
    with psycopg.connect(url, connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cur.execute("SET LOCAL statement_timeout = '30s'")
            cur.execute(SQL_COUNT, (list(STOCKS), START, END))
            count = cur.fetchone()[0]
            if type(count) is not int or not 0 <= count <= MAX_ROWS:
                raise ValueError("Too many events for bounded safe inventory")
            cur.execute(SQL_ACTIONS, (list(STOCKS), START, END, MAX_ROWS + 1))
            columns = [item.name for item in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        conn.rollback()
    return count, rows


def main():
    cli = argparse.ArgumentParser(
        description="Owner 2327+2603 corporate actions coverage READ ONLY; release blocked")
    cli.add_argument("--sma-report", required=True)
    cli.add_argument("--out", required=True)
    a = cli.parse_args()
    try:
        source = _private_file(a.sma_report, should_exist=True)
        output = _private_file(a.out, should_exist=False)
        if source == output:
            raise ValueError("Never overwrite owner source evidence")
        prior = json.loads(source.read_text(encoding="utf-8"))
        validate_prior_sma_report(prior)  # Refuse before connecting to Neon.
        n, rows = read_existing_neon_actions()
        result = assess_recorded_actions(prior, rows, total_rows=n)
        with output.open("x", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False, allow_nan=False)
            f.write("\n")
        print(json.dumps({
            "status": "2022_TWO_STOCK_RECORDED_ACTION_COVERAGE_READONLY_AUDIT_PASS",
            "stocks": 2,
            "stored_events": result["actual_readonly_stored_action_rows"],
            "complete_dividend_history_proven": False,
            "total_return_model_approved": False,
            "neon_writes": 0,
            "line_messages_sent": 0,
            "model_release": "BLOCKED",
        }, ensure_ascii=False))
    except Exception:
        raise SystemExit(
            "Private 2021-22 event coverage audit FAILED; no production writes, "
            "LINE messages or credentials printed"
        ) from None


if __name__ == "__main__":
    main()
