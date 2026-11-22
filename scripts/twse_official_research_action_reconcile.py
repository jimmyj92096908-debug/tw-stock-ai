"""Offline, bounded reconciliation of monthly official ex-action previews to TWSE raw-research windows.

Takes outputs from official_dividend_monthly_preview.py generated on the owner's PC.
Preview capture is *not* issuer announcement vintage, complete dividend history,
or independently certified adjusted total-return labels. No DB connection/writes.
"""
from __future__ import annotations

import argparse
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re

EXPECTED_STOCKS = 20
EXPECTED_WINDOWS = 10
MAX_MONTHS = 6
MAX_MONTH_FILE_BYTES = 4_000_000
MAX_DATASET_BYTES = 12_000_000
EXACT_SOURCES = {
    ("twse", "ex"): {"https://www.twse.com.tw/rwd/zh/exRight/TWT49U"},
    ("twse", "reduction"): {"https://www.twse.com.tw/exchangeReport/TWTAUU"},
    ("tpex", "ex"): {
        "https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ",
        "https://www.tpex.org.tw/web/stock/exright/dailyquo/exDailyQ_result.php",
    },
    ("tpex", "reduction"): {"https://www.tpex.org.tw/www/zh-tw/bulletin/revivt"},
}
ACTION_TYPES = {"CASH_DIVIDEND", "STOCK_DIVIDEND", "COMBINED_OR_UNKNOWN", "CAPITAL_REDUCTION"}
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def load(path: Path, cap: int) -> tuple[dict, str]:
    if not path.is_file() or path.stat().st_size > cap:
        raise ValueError("Missing or oversized private research evidence file")
    raw = path.read_bytes()
    obj = json.loads(raw.decode("utf-8-sig"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
    if not isinstance(obj, dict):
        raise ValueError("Evidence must be a JSON object")
    return obj, sha256(raw).hexdigest()


def require_date(value) -> date:
    if not isinstance(value, str):
        raise ValueError("ISO calendar day required")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("Noncanonical ISO calendar day")
    return parsed


def month_windows(start: date, end: date) -> list[tuple[date, date]]:
    if start > end or (end-start).days > 185:
        raise ValueError("Research date bounds invalid or too large")
    cur = start.replace(day=1)
    periods = []
    while cur <= end:
        stop = min(end, cur.replace(day=monthrange(cur.year, cur.month)[1]))
        periods.append((cur, stop))
        cur = stop + timedelta(days=1)
        if len(periods) > MAX_MONTHS:
            raise ValueError("Monthly official evidence cap exceeded")
    return periods


def validate_study(dataset, fixed, expanding, readiness):
    if dataset.get("market") != "twse":
        raise ValueError("Study must be the frozen TWSE research universe")
    roster = dataset.get("frozen_current_stock_roster")
    if (not isinstance(roster, list) or len(roster) != EXPECTED_STOCKS
            or len(set(roster)) != EXPECTED_STOCKS
            or any(not isinstance(s, str) or not re.fullmatch(r"[0-9]{4}", s) for s in roster)
            or "1589" in roster):
        raise ValueError("Invalid or excluded frozen current-listed cohort")
    rows = dataset.get("rows")
    if not isinstance(rows, list) or len(rows) < 20 * EXPECTED_WINDOWS:
        raise ValueError("Research dataset rows incomplete")
    normalized = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if sha256(normalized).hexdigest() != dataset.get("rows_sha256"):
        raise ValueError("Research rows fingerprint mismatch")
    if (dataset.get("price_labels_adjusted_for_cash_dividends_or_splits") is not False
            or fixed.get("label_is_adjusted_total_return") is not False
            or expanding.get("price_labels_adjusted_for_dividends") is not False):
        raise ValueError("Research cannot claim certified total-return labels")
    fw, ew = fixed.get("nonoverlap_test_windows"), expanding.get("nonoverlap_windows")
    if (not isinstance(fw, list) or not isinstance(ew, list)
            or len(fw) != EXPECTED_WINDOWS or len(ew) != EXPECTED_WINDOWS):
        raise ValueError("Requires original ten windows from both models")
    known = set(roster)
    windows = []
    previous_exit = None
    for f, e in zip(fw, ew):
        if any(f.get(k) != e.get(k) for k in ("signal_date", "entry_date", "exit_date")):
            raise ValueError("Fixed/expanding date mismatch")
        signal, entry, exit_day = (require_date(f[k]) for k in ("signal_date", "entry_date", "exit_date"))
        if not signal < entry < exit_day or (previous_exit is not None and signal <= previous_exit):
            raise ValueError("Overlapping or noncausal model windows")
        if require_date(e["last_mature_training_exit"]) >= signal:
            raise ValueError("Future-training-label leakage")
        members = [r for r in rows if r.get("as_of_date") == signal.isoformat()]
        if (len(members) != EXPECTED_STOCKS
                or {r.get("stock_id") for r in members} != known
                or {r.get("entry_date") for r in members} != {entry.isoformat()}
                or {r.get("exit_date") for r in members} != {exit_day.isoformat()}):
            raise ValueError("Research members and holding dates disagree")
        windows.append({"signal_date": signal.isoformat(), "entry_date": entry.isoformat(),
                        "exit_date": exit_day.isoformat()})
        previous_exit = exit_day
    start, end = windows[0]["entry_date"], windows[-1]["exit_date"]
    if (readiness.get("release_decision") != "BLOCKED"
            or readiness.get("historical_total_return_labels_verified") is not False
            or readiness.get("research_stocks") != EXPECTED_STOCKS
            or readiness.get("research_windows") != EXPECTED_WINDOWS
            or readiness.get("entry_date_min") != start
            or readiness.get("exit_date_max") != end
            or readiness.get("database_read_only") is not True
            or readiness.get("database_writes") != 0
            or readiness.get("line_messages_sent") != 0):
        raise ValueError("Original live-readonly readiness receipt not verified")
    return set(roster), windows, month_windows(require_date(start), require_date(end))


def require_int(obj, key):
    v = obj.get(key)
    if type(v) is not int or v < 0:
        raise ValueError("Invalid official source count: " + key)
    return v


def require_float_or_none(value, label):
    if value is None:
        return
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("Invalid source amount or factor: " + label)


def inspect_month(report, expected_start: date, expected_end: date):
    if (report.get("schema_version") != 1
            or report.get("scope") != "TWSE_TPEX_CURRENT_OFFICIAL_EXRIGHT_MONTHLY_EVIDENCE_NOT_TOTAL_RETURN"
            or require_date(report.get("query_from")) != expected_start
            or require_date(report.get("query_to")) != expected_end):
        raise ValueError("Missing or mismatched exact official monthly evidence period")
    captured = datetime.fromisoformat(report["first_seen_at_utc"].replace("Z", "+00:00"))
    if captured.tzinfo is None or captured.astimezone(timezone.utc).date() < expected_end:
        raise ValueError("Source observation is missing its real later capture timestamp")
    if (report.get("verified_total_return_labels") is not False
            or report.get("raw_price_labels_still_unadjusted") is not True
            or report.get("no_historical_issuer_publication_vintages_in_feed") is not True
            or report.get("not_full_five_year_issuer_or_dividend_coverage") is not True
            or report.get("production_corporate_actions_modified") is not False
            or report.get("database_writes") != 0
            or report.get("LINE_or_trading_enabled") is not False
            or report.get("paid_data_used") is not False):
        raise ValueError("Monthly preview provenance/safety flags missing")
    ev = report.get("source_evidence")
    if not isinstance(ev, list) or len(ev) != 4:
        raise ValueError("Four official TWSE/TPEx source responses mandatory")
    seen = set()
    counted = 0
    for src in ev:
        key = (src.get("market"), src.get("kind"))
        if key not in EXACT_SOURCES or key in seen or src.get("source") not in EXACT_SOURCES[key]:
            raise ValueError("Official source ID missing or spoofed")
        seen.add(key)
        total = require_int(src, "received_rows")
        included = require_int(src, "four_digit_candidates")
        excluded1 = require_int(src, "excluded_outside_requested_date_range")
        excluded2 = require_int(src, "excluded_non_common_stock_or_unknown")
        if included + excluded1 + excluded2 != total:
            raise ValueError("Source response counts inconsistent")
        counted += included
    candidates = report.get("candidates")
    if not isinstance(candidates, list) or len(candidates) > 8000:
        raise ValueError("Missing or oversized monthly candidate list")
    if (require_int(report, "raw_four_digit_source_events") != counted
            or require_int(report, "distinct_candidate_economic_events") != len(candidates)
            or require_int(report, "duplicate_economic_feed_records") != counted - len(candidates)):
        raise ValueError("Monthly original and deduplicated event rows differ")
    identities = set()
    for ev in candidates:
        if not isinstance(ev, dict):
            raise ValueError("Official candidate is not a record")
        market, sid = ev.get("market"), ev.get("stock_id")
        ex_date = require_date(ev.get("ex_date"))
        kind = ev.get("action_type_candidate")
        if (market not in ("twse", "tpex")
                or not isinstance(sid, str) or not re.fullmatch(r"[0-9]{4}", sid)
                or ex_date < expected_start or ex_date > expected_end
                or kind not in ACTION_TYPES
                or not any(ev.get("official_source") in s for (m, _), s in EXACT_SOURCES.items() if m == market)
                or not isinstance(ev.get("source_raw_record_sha256"), str)
                or not SHA256_RE.fullmatch(ev["source_raw_record_sha256"])
                or ev.get("issuer_original_announcement_time_verified") is not False
                or ev.get("historical_total_return_adjustment_verified") is not False):
            raise ValueError("Invalid official candidate date/origin or false PIT certification")
        require_float_or_none(ev.get("reference_price_factor_if_available"), "price factor")
        require_float_or_none(ev.get("explicit_cash_dividend_per_share"), "cash dividend")
        require_float_or_none(ev.get("share_exchange_per_thousand_if_available"), "share exchange")
        identity = (market, sid, ex_date.isoformat(), kind,
                    ev.get("reference_price_factor_if_available"),
                    ev.get("explicit_cash_dividend_per_share"),
                    ev.get("share_exchange_per_thousand_if_available"))
        if identity in identities:
            raise ValueError("Duplicate candidate retained after supposed monthly dedup")
        identities.add(identity)
    return candidates, counted


def reconcile(*, dataset, fixed, expanding, readiness, reports):
    roster, windows, expected_periods = validate_study(dataset, fixed, expanding, readiness)
    if len(reports) != len(expected_periods):
        raise ValueError("Require one evidence file per research calendar month")
    all_candidates = []
    raw_source_rows = 0
    for (start, end), report in zip(expected_periods, reports):
        candidates, n = inspect_month(report, start, end)
        all_candidates.extend(candidates)
        raw_source_rows += n
    cohort = [c for c in all_candidates if c["market"] == "twse" and c["stock_id"] in roster]
    cohort.sort(key=lambda c: (c["ex_date"], c["stock_id"], c["action_type_candidate"]))
    flags = []
    for w in windows:
        matched = [c for c in cohort if w["entry_date"] <= c["ex_date"] <= w["exit_date"]]
        flags.append({
            "signal_date": w["signal_date"], "entry_date": w["entry_date"],
            "exit_date": w["exit_date"],
            "official_candidate_events_near_holding_period": len(matched),
            "stocks_with_candidates": sorted({c["stock_id"] for c in matched}),
            "candidate_on_entry_day_possible_no_dividend_entitlement": sum(
                c["ex_date"] == w["entry_date"] for c in matched),
            "raw_price_label_independently_reconciled": False,
        })
    return {
        "schema_version": 1,
        "scope": "TWSE_20_STOCK_OFFICIAL_EX_ACTION_CANDIDATE_RECONCILIATION",
        "study_start": windows[0]["entry_date"],
        "study_end": windows[-1]["exit_date"],
        "official_preview_periods_structurally_present": len(expected_periods),
        "official_feeds_per_period": 4,
        "total_four_digit_source_candidate_rows": raw_source_rows,
        "twse_research_cohort_candidate_events": len(cohort),
        "research_windows_with_event_candidate": sum(bool(x["official_candidate_events_near_holding_period"]) for x in flags),
        "candidate_events": [{
            "stock_id": c["stock_id"], "ex_date": c["ex_date"],
            "action_type_candidate": c["action_type_candidate"],
            "reference_price_factor_if_available": c["reference_price_factor_if_available"],
            "explicit_cash_dividend_per_share": c["explicit_cash_dividend_per_share"],
            "official_source": c["official_source"],
            "source_raw_record_sha256": c["source_raw_record_sha256"],
        } for c in cohort],
        "window_candidate_overlap": flags,
        "no_preview_event_does_not_prove_no_actual_action": True,
        "monthly_source_files_not_independently_authenticated": True,
        "historical_issuer_announcement_vintage_verified": False,
        "historical_point_in_time_universe_verified": False,
        "true_total_return_label_verified": False,
        "independent_future_holdout_passed": False,
        "release_decision": "BLOCKED",
        "database_connections": 0,
        "database_writes": 0,
        "line_messages_sent": 0,
        "paid_services_used": False,
    }


def main():
    p = argparse.ArgumentParser(description="Offline official monthly ex-action evidence reconciliation, no model release")
    p.add_argument("--dataset", required=True, type=Path)
    p.add_argument("--fixed", required=True, type=Path)
    p.add_argument("--expanding", required=True, type=Path)
    p.add_argument("--readiness", required=True, type=Path)
    p.add_argument("--monthly", required=True, nargs="+", type=Path)
    p.add_argument("--out", required=True, type=Path)
    a = p.parse_args()
    if len(a.monthly) > MAX_MONTHS or len(set(a.monthly)) != len(a.monthly):
        raise ValueError("Duplicate or excessive monthly source files")
    dataset, dataset_sha = load(a.dataset, MAX_DATASET_BYTES)
    fixed, fixed_sha = load(a.fixed, MAX_DATASET_BYTES)
    expanding, expanding_sha = load(a.expanding, MAX_DATASET_BYTES)
    readiness, readiness_sha = load(a.readiness, 50_000)
    months = [load(path, MAX_MONTH_FILE_BYTES) for path in a.monthly]
    report = reconcile(dataset=dataset, fixed=fixed, expanding=expanding,
                       readiness=readiness, reports=[r for r, _ in months])
    report["local_file_sha256_receipts_not_source_authentication"] = {
        "dataset": dataset_sha, "fixed": fixed_sha, "expanding": expanding_sha,
        "readiness": readiness_sha, "official_monthly": [x[1] for x in months],
    }
    if a.out.exists():
        raise FileExistsError("Audit output already exists; cannot overwrite")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("x", encoding="utf-8") as fd:
        json.dump(report, fd, ensure_ascii=False, indent=2, allow_nan=False)
        fd.write("\n")
    print(json.dumps({
        "audit_structure_pass": True,
        "official_preview_periods": report["official_preview_periods_structurally_present"],
        "cohort_candidate_events": report["twse_research_cohort_candidate_events"],
        "windows_with_candidate_events": report["research_windows_with_event_candidate"],
        "true_total_return_label_verified": False,
        "release_decision": "BLOCKED", "database_writes": 0,
        "line_messages_sent": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
