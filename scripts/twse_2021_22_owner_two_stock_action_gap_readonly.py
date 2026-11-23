"""Owner-private 1101/2330 2021-22 missing corporate-action evidence audit.

Requires the TWO already-successful original-price AES+Neon private receipts.
One protected Neon READ ONLY snapshot; static dated public candidate evidence.
This does NOT authenticate an original issuer publication timestamp, guarantee
historical corporate-action completeness or compute adjusted total returns.
Never writes SQL, LINE, stock prices, or key material; no paid operations.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path

from scripts.twse_2021_22_traded_240_warmup_readonly import _private_file
from scripts.twse_2022_aes_neon_eligible_density_readonly import ELIGIBLE_SQL
from scripts.twse_2021_22_owner_virtual_2330_prefix_readonly import (
    SCOPE as SCOPE_2330, SCOPE_1101,
)

STOCKS = ("1101", "2330")
START = date(2021, 11, 23)
END = date(2022, 12, 30)
SCOPE = "OWNER_2021_22_1101_2330_DATED_ACTION_GAPS_READONLY"
MAX_EVENTS = 100
MAX_PRIVATE_OUTPUT = 12000

# Public *retrospective* event ledger. 1101 ex-date from a third-party
# historical table is explicitly only a CANDIDATE, NOT original issuer/PIT.
# TSMC's issuer dividend-history page independently lists 5 ex-dates.
# No amount, entitlement, adjusted factor or announcement vintage is inferred.
CANDIDATES = (
    ("1101", date(2022, 7, 21), "CASH_AND_STOCK_CANDIDATE",
     "THIRD_PARTY_RETROSPECTIVE",
     "https://goodinfo.tw/tw/StockDividendSchedule.asp?STOCK_ID=1101"),
    ("2330", date(2021, 12, 16), "CASH_DIVIDEND",
     "ISSUER_RETROSPECTIVE",
     "https://investor.tsmc.com/chinese/dividends"),
    ("2330", date(2022, 3, 16), "CASH_DIVIDEND",
     "ISSUER_RETROSPECTIVE",
     "https://investor.tsmc.com/chinese/dividends"),
    ("2330", date(2022, 6, 16), "CASH_DIVIDEND",
     "ISSUER_RETROSPECTIVE",
     "https://investor.tsmc.com/chinese/dividends"),
    ("2330", date(2022, 9, 15), "CASH_DIVIDEND",
     "ISSUER_RETROSPECTIVE",
     "https://investor.tsmc.com/chinese/dividends"),
    ("2330", date(2022, 12, 15), "CASH_DIVIDEND",
     "ISSUER_RETROSPECTIVE",
     "https://investor.tsmc.com/chinese/dividends"),
)

COUNT_ACTION_SQL = """
SELECT COUNT(*)::int AS n FROM public.corporate_actions
WHERE market='twse' AND stock_id=ANY(%s::varchar[])
AND ex_date BETWEEN %s AND %s
"""
ACTION_SQL = """
SELECT stock_id,ex_date,action_type,verified
FROM public.corporate_actions
WHERE market='twse' AND stock_id=ANY(%s::varchar[])
AND ex_date BETWEEN %s AND %s
ORDER BY stock_id,ex_date,action_type,source_event_id
LIMIT 101
"""
PRICE_DENSITY_SQL = """
SELECT stock_id,
  COUNT(DISTINCT trade_date) FILTER (WHERE trade_date < DATE '2022-01-01')::int AS y2021,
  COUNT(DISTINCT trade_date) FILTER (WHERE trade_date >= DATE '2022-01-01')::int AS y2022
FROM public.daily_prices
WHERE market='twse' AND stock_id=ANY(%s::varchar[])
AND trade_date BETWEEN DATE '2021-11-23' AND DATE '2022-12-30'
AND source IN ('TWSE_STOCK_DAY','TWSE_MI_INDEX_ALLBUT0999')
AND close>0 AND volume>=0
GROUP BY stock_id ORDER BY stock_id
"""
EVENT_DAY_SQL = """
SELECT stock_id,trade_date,COUNT(*)::int AS n
FROM public.daily_prices
WHERE market='twse' AND stock_id=ANY(%s::varchar[])
AND trade_date=ANY(%s::date[])
AND source IN ('TWSE_STOCK_DAY','TWSE_MI_INDEX_ALLBUT0999')
AND close>0 AND volume>=0
GROUP BY stock_id,trade_date ORDER BY stock_id,trade_date
LIMIT 20
"""

STAGES = frozenset({
    "PRIVATE_RECEIPTS", "PRIOR_RECEIPT_GUARD", "NEON_READONLY_SNAPSHOT",
    "OFFICIAL_EVENT_GAP_RECONCILIATION", "PRIVATE_REPORT_WRITE", "UNCLASSIFIED",
})


class ActionGapStageError(ValueError):
    def __init__(self, code):
        self.code = code if code in STAGES else "UNCLASSIFIED"
        super().__init__(self.code)


def _phase(code, fn, *args, **kwargs):
    if code not in STAGES:
        raise ActionGapStageError("UNCLASSIFIED")
    try:
        return fn(*args, **kwargs)
    except ActionGapStageError:
        raise
    except Exception:
        raise ActionGapStageError(code) from None


def _fail(code):
    code = code if code in STAGES else "UNCLASSIFIED"
    return ("Owner 1101/2330 2021/22 action-gap READ ONLY FAILED safely; "
            "diagnostic_stage=" + code
            + "; no owner price, private path, key or Neon URI disclosed")


def validate_prior_receipts(prior):
    if not isinstance(prior, dict) or set(prior) != set(STOCKS):
        raise ValueError("Two exact previous private AES+Neon issuer receipts required")
    for sid in STOCKS:
        x = prior[sid]
        overlap = ("neon_AES_overlapping_2330_source_stockdate_keys"
                   if sid == "2330" else "neon_AES_overlapping_stockdate_keys")
        scope = SCOPE_2330 if sid == "2330" else SCOPE_1101
        if (not isinstance(x, dict)
                or x.get("stock_id") != sid or x.get("scope") != scope
                or x.get("schema_version") != 1
                or x.get("as_of") != END.isoformat()
                or x.get("virtual_2021_22_combined_source_days") != 274
                or x.get("virtual_2022_source_calendar_days") != 246
                or x.get(overlap) != 190
                or x.get("neon_AES_overlap_OHLCV_exact") is not True
                or x.get("as_of_raw_prefix_source_days") != 274
                or x.get("source_rows_after_asof_used_in_computation") != 0
                or x.get("raw_unadjusted_sma240_is_tradable_signal") is not False
                or x.get("all_five_year_market_data_complete") is not False
                or x.get("survivorship_free_historical_universe_verified") is not False
                or x.get("corporate_action_and_publication_vintage_verified") is not False
                or x.get("authoritative_holdout_alpha_verified") is not False
                or x.get("production_backfill_approved") is not False
                or x.get("neon_writes") != 0
                or x.get("line_messages_sent") != 0
                or x.get("paid_services_used") is not False
                or x.get("model_release") != "BLOCKED"):
            raise ValueError("Prior issuer raw-price receipt is not the accepted blocked source proof")
    # Owner JSON receipt checks do not reauthenticate ciphertext; avoid
    # mislabelling a past plaintext receipt as an independent cold restore.
    return True


def capture_snapshot(url):
    if not isinstance(url, str) or not url.startswith(("postgresql://", "postgres://")):
        raise ValueError("Owner private Neon DATABASE_URL required")
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(url, connect_timeout=15, row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='30000ms'")
        roster = [r["stock_id"] for r in conn.execute(ELIGIBLE_SQL).fetchall()]
        if (len(roster) != 1092 or not set(STOCKS).issubset(roster)
                or "1589" in roster):
            raise ValueError("Current listed universe or excluded issuer drifted")
        params = (list(STOCKS), START, END)
        total = conn.execute(COUNT_ACTION_SQL, params).fetchone()["n"]
        if type(total) is not int or not 0 <= total <= MAX_EVENTS:
            raise ValueError("Incomplete or excessive corporate action query bound")
        actions = [dict(r) for r in conn.execute(ACTION_SQL, params).fetchall()]
        if len(actions) != total:
            raise ValueError("Corporate action count changed within source snapshot")
        density = [dict(r) for r in conn.execute(
            PRICE_DENSITY_SQL, (list(STOCKS),)).fetchall()]
        event_dates = sorted({day for _, day, *_ in CANDIDATES})
        event_days = [dict(r) for r in conn.execute(
            EVENT_DAY_SQL, (list(STOCKS), event_dates)).fetchall()]
    return actions, density, event_days


def evaluate(*, prior, actions, density, event_days):
    """No private prices or amounts; retrospective dates never certify PIT."""
    validate_prior_receipts(prior)
    if (not isinstance(actions, list) or not isinstance(density, list)
            or not isinstance(event_days, list) or len(actions) > MAX_EVENTS):
        raise ValueError("Bounded raw action and source inventories required")
    if ({r.get("stock_id") for r in density} != set(STOCKS)
            or len(density) != 2
            or any(r.get("y2021") != 28 or r.get("y2022") != 246
                   for r in density)):
        raise ValueError("Current two issuer Neon 274-day source coverage drifted")
    expected = {(s, d) for s, d, *_ in CANDIDATES}
    seen = set()
    for r in event_days:
        if (not isinstance(r, dict) or type(r.get("trade_date")) is not date
                or (r.get("stock_id"), r.get("trade_date")) not in expected
                or type(r.get("n")) is not int or r["n"] != 1):
            raise ValueError("Missing or duplicated real source bar on retrospective event date")
        key = (r["stock_id"], r["trade_date"])
        if key in seen:
            raise ValueError("Duplicate source-day witness")
        seen.add(key)
    if seen != expected:
        raise ValueError("Insufficient historical daily source bars on dated event candidates")

    grouped = {sid: [] for sid in STOCKS}
    for r in actions:
        if (not isinstance(r, dict) or r.get("stock_id") not in STOCKS
                or type(r.get("ex_date")) is not date
                or not START <= r["ex_date"] <= END
                or not isinstance(r.get("action_type"), str)
                or not r["action_type"] or type(r.get("verified")) is not bool):
            raise ValueError("Unexpected stored action or unverifiable provenance")
        grouped[r["stock_id"]].append(r)
    known = []
    for sid, day, typ, strength, link in CANDIDATES:
        same = [a for a in grouped[sid] if a["ex_date"] == day]
        known.append({
            "stock_id": sid, "candidate_ex_date": day.isoformat(),
            "retrospective_event_category": typ,
            "retrospective_evidence_tier": strength,
            "public_source": link,
            "official_raw_stock_day_exists": True,
            "same_date_stored_action_rows": len(same),
            "same_date_stored_verified_action_rows": sum(
                x["verified"] is True for x in same),
            "status": ("NO_ACTION_RECORD_ON_CANDIDATE_DATE"
                       if not same else "RECORDED_ACTION_EXISTS_UNRECONCILED"),
            "complete_event_amount_or_share_economics_verified": False,
            "original_issuer_announcement_publication_timestamp_verified": False,
            "historical_total_return_label_approved": False,
        })
    return {
        "schema_version": 1,
        "scope": SCOPE,
        "window_start": START.isoformat(), "window_end": END.isoformat(),
        "current_eligible_stocks": list(STOCKS),
        "private_prior_2330_and_1101_raw_source_receipts_guard_passed": True,
        "prior_receipts_are_cryptographically_reauthenticated_here": False,
        "neon_issuer_raw_source_days": {d["stock_id"]: 274 for d in density},
        "stored_action_rows_in_entire_two_stock_window": len(actions),
        "stored_action_rows_by_stock": {sid: len(grouped[sid]) for sid in STOCKS},
        "historical_candidate_event_dates": len(CANDIDATES),
        "candidate_dates_without_stored_action": sum(
            r["same_date_stored_action_rows"] == 0 for r in known),
        "candidate_date_witnesses": known,
        "retrospective_event_date_is_original_publication_vintage": False,
        "known_event_candidates_prove_complete_action_universe": False,
        "stock_dividend_adjustments_verified": False,
        "cash_dividend_entitlement_and_payment_verified": False,
        "capital_reduction_and_split_universe_verified": False,
        "tax_fee_reinvestment_and_total_return_verified": False,
        "adjusted_prices_or_raw_sma240_promoted_to_trading_signal": False,
        "real_future_return_labels_approved": False,
        "production_backfill_approved": False,
        "model_release": "BLOCKED",
        "neon_writes": 0,
        "line_messages_sent": 0,
        "paid_services_requested": False,
    }


def run_owner(*, report_2330, report_1101, out, database_url):
    file_2330 = _phase("PRIVATE_RECEIPTS", _private_file, report_2330, should_exist=True)
    file_1101 = _phase("PRIVATE_RECEIPTS", _private_file, report_1101, should_exist=True)
    output = _phase("PRIVATE_RECEIPTS", _private_file, out, should_exist=False)
    if len({file_2330, file_1101, output}) != 3:
        raise ActionGapStageError("PRIVATE_RECEIPTS")
    prior = {
        "2330": _phase("PRIOR_RECEIPT_GUARD", lambda: json.loads(
            file_2330.read_text(encoding="utf-8"))),
        "1101": _phase("PRIOR_RECEIPT_GUARD", lambda: json.loads(
            file_1101.read_text(encoding="utf-8"))),
    }
    _phase("PRIOR_RECEIPT_GUARD", validate_prior_receipts, prior)
    actions, density, day_rows = _phase(
        "NEON_READONLY_SNAPSHOT", capture_snapshot, database_url)
    result = _phase(
        "OFFICIAL_EVENT_GAP_RECONCILIATION", evaluate,
        prior=prior, actions=actions, density=density, event_days=day_rows)
    data = _phase("PRIVATE_REPORT_WRITE", lambda:
                  json.dumps(result, ensure_ascii=False, indent=2,
                             allow_nan=False) + "\n")
    if len(data.encode("utf-8")) > MAX_PRIVATE_OUTPUT:
        raise ActionGapStageError("PRIVATE_REPORT_WRITE")
    def store():
        with output.open("x", encoding="utf-8") as f:
            f.write(data)
    _phase("PRIVATE_REPORT_WRITE", store)
    print(json.dumps({
        "status": "OWNER_1101_2330_DATED_ACTION_GAP_READONLY_PASS",
        "known_retrospective_event_candidates": len(CANDIDATES),
        "candidates_without_stored_action": result[
            "candidate_dates_without_stored_action"],
        "complete_action_history_verified": False,
        "adjusted_total_return_approved": False,
        "model_release": "BLOCKED",
        "neon_writes": 0, "line_messages_sent": 0,
    }, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prior-2330", required=True)
    p.add_argument("--prior-1101", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        raise SystemExit(_fail("UNCLASSIFIED"))
    try:
        run_owner(
            report_2330=args.prior_2330, report_1101=args.prior_1101,
            out=args.out, database_url=os.environ.get("DATABASE_URL", ""))
    except ActionGapStageError as e:
        raise SystemExit(_fail(e.code)) from None
    except Exception:
        raise SystemExit(_fail("UNCLASSIFIED")) from None


if __name__ == "__main__":
    main()
