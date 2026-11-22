"""Offline classification of TWSE 2022 issuer-specific cash-reduction halts.

Only reads an existing owner-private AES x read-only Neon diagnostics JSON.
No market downloads, DB connections, synthetic prices, adjusted returns,
production score changes, or LINE messages.

Contemporaneous coverage of issuer notices / TWSE announcements:
2327: https://www.cna.com.tw/news/afe/202209130344.aspx
2603: https://www.cna.com.tw/news/afe/202208230303.aspx
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re

EXPECTED_SCOPE = "TWSE_2022_LOCAL_AES_EXISTING_NEON_READONLY_FROZEN20_FACTOR_RESEARCH"
EXPECTED_HALT_SESSIONS = {
    "2327": (
        "2022-10-20", "2022-10-21", "2022-10-24", "2022-10-25",
        "2022-10-26", "2022-10-27", "2022-10-28",
    ),
    "2603": (
        "2022-09-07", "2022-09-08", "2022-09-12", "2022-09-13",
        "2022-09-14", "2022-09-15", "2022-09-16",
    ),
}
CONTEMPORANEOUS_EVIDENCE = {
    "2327": {
        "published": "2022-09-13",
        "reference": "https://www.cna.com.tw/news/afe/202209130344.aspx",
        "resume_date": "2022-10-31",
    },
    "2603": {
        "published": "2022-08-23",
        "reference": "https://www.cna.com.tw/news/afe/202208230303.aspx",
        "resume_date": "2022-09-19",
    },
}


def classify(report):
    """Classify only exact documented issuer halt dates; remain BLOCKED."""
    if (not isinstance(report, dict)
            or report.get("schema_version") != 1
            or report.get("scope") != EXPECTED_SCOPE
            or report.get("live_model_release_decision") != "BLOCKED"
            or report.get("neon_transaction_mode") != "READ_ONLY"
            or type(report.get("neon_write_operations")) is not int
            or report["neon_write_operations"] != 0
            or type(report.get("line_messages_sent")) is not int
            or report["line_messages_sent"] != 0
            or report.get("complete_five_year_history_verified") is not False
            or report.get("dividends_splits_or_total_return_adjusted") is not False
            or report.get("sma240_stock_day_gap_diagnostics_available") is not True):
        raise ValueError("Not an eligible blocked read-only 2022 evidence report")

    sessions = report.get("unique_observed_2022_source_sessions")
    incomplete = report.get("missing_sma240_stock_count")
    stock_count = report.get("frozen_current_research_stock_count")
    complete = report.get("frozen_stocks_with_complete_last_240_source_sessions")
    details = report.get("missing_sma240_stock_day_details")
    if (type(sessions) is not int or not 240 <= sessions <= 260
            or type(stock_count) is not int or stock_count != 20
            or type(incomplete) is not int or not 0 <= incomplete <= 20
            or type(complete) is not int or complete + incomplete != stock_count
            or not isinstance(details, list) or len(details) != incomplete):
        raise ValueError("Invalid bounded 240-session research summary")

    classified, unknown, seen = [], [], set()
    for entry in details:
        if not isinstance(entry, dict):
            raise ValueError("Invalid stock-day evidence")
        sid = entry.get("stock_id")
        missing_dates = entry.get("missing_observed_trade_dates")
        count = entry.get("missing_observed_trade_day_count")
        if (not isinstance(sid, str) or not re.fullmatch(r"[0-9]{4}", sid)
                or sid == "1589" or sid in seen
                or not isinstance(missing_dates, list)
                or not 1 <= len(missing_dates) <= 260
                or type(count) is not int or count != len(missing_dates)
                or entry.get("source_refetch_or_neon_write_authorized") is not False):
            raise ValueError("Invalid/duplicated/unapproved stock-day evidence")
        seen.add(sid)
        if len(set(missing_dates)) != len(missing_dates):
            raise ValueError("Duplicate stock-day dates")
        for value in missing_dates:
            if not isinstance(value, str):
                raise ValueError("Invalid date type")
            try:
                d = date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError("Invalid ISO date") from exc
            if d.isoformat() != value or d.year != 2022 or d.weekday() >= 5:
                raise ValueError("Not a valid observed 2022 trading weekday")
            if value in EXPECTED_HALT_SESSIONS.get(sid, ()):
                proof = CONTEMPORANEOUS_EVIDENCE[sid]
                classified.append({
                    "stock_id": sid,
                    "trade_date": value,
                    "classification": "CASH_CAPITAL_REDUCTION_SHARE_EXCHANGE_NO_STOCK_TRADING",
                    "historical_announcement_reference": proof["reference"],
                    "original_evidence_publication_date": proof["published"],
                    "new_shares_resumed_trading": proof["resume_date"],
                    "synthetic_price_or_market_bar_created": False,
                })
            else:
                unknown.append({
                    "stock_id": sid, "trade_date": value,
                    "classification": "UNRESOLVED_DO_NOT_BACKFILL",
                })
    classified.sort(key=lambda row: (row["stock_id"], row["trade_date"]))
    unknown.sort(key=lambda row: (row["stock_id"], row["trade_date"]))
    return {
        "scope": "2022_TWSE_FROZEN20_KNOWN_CASH_REDUCTION_HALTS_OFFLINE_EVIDENCE",
        "source_scope": EXPECTED_SCOPE,
        "source_observed_market_sessions": sessions,
        "source_sma240_complete_stock_count_unchanged": complete,
        "source_sma240_incomplete_stock_count_unchanged": incomplete,
        "known_cash_reduction_stock_halt_days": len(classified),
        "stock_ids_with_known_cash_reduction_halts":
            sorted({row["stock_id"] for row in classified}),
        "classified_halt_stock_day_details": classified,
        "unknown_stock_day_count": len(unknown),
        "unknown_stock_days": unknown,
        "all_reported_gap_dates_explained_by_known_halts": not unknown,
        "stock_day_halt_is_not_exchange_holiday": True,
        "sma240_recomputed": False,
        "cash_reduction_and_total_return_price_adjustment_performed": False,
        "historic_point_in_time_membership_proven": False,
        "more_real_pre_2022_stock_sessions_may_be_needed_for_240_trades": True,
        "neon_writes": 0,
        "line_messages_sent": 0,
        "extra_paid_services": False,
        "live_model_release_decision": "BLOCKED",
    }


def _private_path(path, *, existing):
    p = Path(path).expanduser()
    if p.is_symlink() or any((a / ".git").exists() for a in (p.parent, *p.parents)):
        raise ValueError("Git checkout / symlink forbidden for private reports")
    p = p.resolve()
    if existing:
        if not p.is_file() or p.stat().st_size > 256_000:
            raise ValueError("Bounded existing private JSON report required")
    elif not p.parent.is_dir() or p.exists():
        raise ValueError("Existing private output directory required; no overwrite")
    return p


def main():
    parser = argparse.ArgumentParser(
        description="Offline cash-reduction stock halt evidence; never contacts Neon")
    parser.add_argument("--in", dest="source", type=Path, required=True)
    parser.add_argument("--out", dest="output", type=Path, required=True)
    args = parser.parse_args()
    source = _private_path(args.source, existing=True)
    output = _private_path(args.output, existing=False)
    if source == output:
        raise ValueError("Cannot overwrite source evidence")
    result = classify(json.loads(source.read_text(encoding="utf-8")))
    with output.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps({
        "status": "KNOWN_2022_CASH_REDUCTION_HALT_AUDIT_PASS",
        "classified_halt_days": result["known_cash_reduction_stock_halt_days"],
        "unknown_stock_days": result["unknown_stock_day_count"],
        "sma240_complete_stocks_unchanged":
            result["source_sma240_complete_stock_count_unchanged"],
        "sma240_recomputed": False,
        "neon_writes": 0,
        "line_messages_sent": 0,
        "model_release": "BLOCKED",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
