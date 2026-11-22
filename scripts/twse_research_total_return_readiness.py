"""Read-only TWSE 20-stock research total-return readiness gate.

This checks DB adjustment *coverage*, not economic total-return correctness.
An absent corporate action record NEVER proves the absence of a dividend.
No production changes, LINE messages, model weights, orders, or paid services.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path

EXPECTED_ROSTER = 20
EXPECTED_WINDOWS = 10

PRICE_SQL = """
SELECT COUNT(*)::int AS raw_price_keys,
       COUNT(a.close)::int AS derived_price_keys,
       COUNT(*) FILTER (WHERE a.adjustment_status='UNADJUSTED')::int AS unadjusted_keys,
       COUNT(*) FILTER (WHERE a.adjustment_status IS NULL)::int AS missing_adjustment_status,
       COUNT(*) FILTER (WHERE a.adjustment_status IS NOT NULL
                        AND a.adjustment_status<>'UNADJUSTED')::int AS other_adjustment_status_keys,
       COUNT(*) FILTER (WHERE a.close IS NOT NULL AND a.close<>p.close)::int AS different_close_keys,
       COUNT(DISTINCT p.stock_id)::int AS stock_count
FROM public.daily_prices p
LEFT JOIN public.daily_adjusted_prices a
  ON (a.market=p.market AND a.stock_id=p.stock_id AND a.trade_date=p.trade_date)
WHERE p.market='twse' AND p.stock_id=ANY(%s::text[])
  AND p.trade_date BETWEEN %s::date AND %s::date
"""
ACTION_SQL = """
SELECT COUNT(*)::int AS stored_event_rows,
       COUNT(*) FILTER (WHERE verified IS TRUE)::int AS verified_event_rows,
       COUNT(*) FILTER (WHERE verified IS NOT TRUE)::int AS unverified_event_rows,
       COUNT(*) FILTER (WHERE created_at::date > ex_date)::int AS first_stored_after_ex_date
FROM public.corporate_actions
WHERE market='twse' AND stock_id=ANY(%s::text[])
  AND ex_date BETWEEN %s::date AND %s::date
"""


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Research artifact must be a JSON object")
    return value


def validate_artifacts(dataset: dict, fixed: dict, expanding: dict):
    if dataset.get("market") != "twse":
        raise ValueError("Only original TWSE research cohort is supported")
    roster = dataset.get("frozen_current_stock_roster")
    if (not isinstance(roster, list) or len(roster) != EXPECTED_ROSTER
            or len(set(roster)) != EXPECTED_ROSTER
            or not all(type(s) is str and len(s) == 4 and s.isdigit() for s in roster)
            or "1589" in roster):
        raise ValueError("Missing, duplicate, excluded or invalid 20-stock roster")
    rows = dataset.get("rows")
    if not isinstance(rows, list):
        raise ValueError("Missing original research rows")
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    if sha256(encoded).hexdigest() != dataset.get("rows_sha256"):
        raise ValueError("Research dataset fingerprint mismatch")
    if (dataset.get("price_labels_adjusted_for_cash_dividends_or_splits") is not False
            or fixed.get("label_is_adjusted_total_return") is not False
            or expanding.get("price_labels_adjusted_for_dividends") is not False):
        raise ValueError("Unverified historical total-return labels cannot be promoted")
    fw = fixed.get("nonoverlap_test_windows")
    ew = expanding.get("nonoverlap_windows")
    if (not isinstance(fw, list) or not isinstance(ew, list)
            or len(fw) != EXPECTED_WINDOWS or len(ew) != EXPECTED_WINDOWS):
        raise ValueError("Expected ten fixed and expanding windows")
    prev_exit = None
    for a, b in zip(fw, ew):
        if any(a.get(k) != b.get(k) for k in ("signal_date", "entry_date", "exit_date")):
            raise ValueError("Fixed and expanding windows are not identical")
        signal, entry, exit_day = (date.fromisoformat(a[k]) for k in
                                   ("signal_date", "entry_date", "exit_date"))
        if not signal < entry < exit_day or (prev_exit and signal <= prev_exit):
            raise ValueError("Overlapping or noncausal research windows")
        if date.fromisoformat(b["last_mature_training_exit"]) >= signal:
            raise ValueError("Expanding research train labels leak future outcomes")
        prev_exit = exit_day

    # Every evaluated window must retain the FULL 20-stock original cohort.
    by_date = {}
    for r in rows:
        if not isinstance(r, dict):
            raise ValueError("Malformed research row")
        if r.get("as_of_date") in {w["signal_date"] for w in fw}:
            by_date.setdefault(r["as_of_date"], []).append(r)
    for w in fw:
        members = by_date.get(w["signal_date"], [])
        if (len(members) != EXPECTED_ROSTER
                or {r["stock_id"] for r in members} != set(roster)
                or {r["entry_date"] for r in members} != {w["entry_date"]}
                or {r["exit_date"] for r in members} != {w["exit_date"]}):
            raise ValueError("Incomplete or misaligned historical research cohort")
    return sorted(roster), fw[0]["entry_date"], fw[-1]["exit_date"]


def evaluate(roster, start, end, prices, actions):
    if len(roster) != EXPECTED_ROSTER or not start < end:
        raise ValueError("Invalid frozen roster or audited dates")
    price_keys = (
        "raw_price_keys", "derived_price_keys", "unadjusted_keys",
        "missing_adjustment_status", "other_adjustment_status_keys",
        "different_close_keys", "stock_count"
    )
    action_keys = (
        "stored_event_rows", "verified_event_rows", "unverified_event_rows",
        "first_stored_after_ex_date"
    )
    if (any(type(prices.get(k)) is not int or prices[k] < 0 for k in price_keys)
            or any(type(actions.get(k)) is not int or actions[k] < 0
                   for k in action_keys)):
        raise ValueError("Incomplete official DB evidence")
    n = prices["raw_price_keys"]
    if (n == 0 or prices["stock_count"] != EXPECTED_ROSTER
            or prices["derived_price_keys"] > n
            or prices["unadjusted_keys"] + prices["other_adjustment_status_keys"]
               + prices["missing_adjustment_status"] != n
            or actions["verified_event_rows"] + actions["unverified_event_rows"]
               != actions["stored_event_rows"]
            or actions["first_stored_after_ex_date"] > actions["stored_event_rows"]):
        raise ValueError("Inconsistent original/derived price or event evidence")
    return {
        "schema_version": 1,
        "scope": "TWSE_20_STOCK_RETROSPECTIVE_TOTAL_RETURN_READINESS_ONLY",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_stocks": EXPECTED_ROSTER,
        "research_windows": EXPECTED_WINDOWS,
        "entry_date_min": start,
        "exit_date_max": end,
        "price_evidence": dict(prices),
        "corporate_action_evidence": dict(actions),
        "verified_current_universe_is_historical_point_in_time": False,
        "absence_of_stored_actions_proves_no_real_dividends": False,
        "derived_prices_prove_cash_total_returns": False,
        "original_issuer_publication_vintage_verified": False,
        "historical_total_return_labels_verified": False,
        "independent_future_validation_passed": False,
        "release_decision": "BLOCKED",
        "research_only": True,
        "database_read_only": True,
        "database_writes": 0,
        "line_messages_sent": 0,
        "production_model_weights_modified": False,
        "paid_upgrade_requested": False,
    }


def read_db(url, roster, start, end):
    if not url or not url.startswith(("postgresql://", "postgres://")):
        raise ValueError("Neon DATABASE_URL must be supplied privately")
    # Lazy import permits completely offline stdlib-only unit tests.
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(url, row_factory=dict_row, connect_timeout=20,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='20000ms'")
        args = (roster, start, end)
        prices = dict(conn.execute(PRICE_SQL, args).fetchone())
        actions = dict(conn.execute(ACTION_SQL, args).fetchone())
    return prices, actions


def main():
    p = argparse.ArgumentParser(description="Read-only TWSE research total-return evidence gate")
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--fixed", type=Path, required=True)
    p.add_argument("--expanding", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    roster, start, end = validate_artifacts(
        _load(a.dataset), _load(a.fixed), _load(a.expanding))
    prices, actions = read_db(os.getenv("DATABASE_URL", ""), roster, start, end)
    report = evaluate(roster, start, end, prices, actions)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps({
        "release_decision": report["release_decision"],
        "raw_price_keys": prices["raw_price_keys"],
        "unadjusted_keys": prices["unadjusted_keys"],
        "stored_event_rows": actions["stored_event_rows"],
        "historical_total_return_labels_verified": False,
        "database_writes": 0,
        "line_messages_sent": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
