"""Offline cross-check of contemporaneously reported 2022 dividends vs Neon inventory.

Reads ONLY the previously accepted private read-only corporate-action counts
for frozen TWSE 2327/2603. It never connects to Neon, fetches external sites,
manufactures cash amounts, writes corporate_actions, adjusts bars or releases
a model. Other existing stock/company events remain uncertified.

A count of >0 cash dividends does NOT establish the specifically dated
2022 event has been stored: the PR#224 aggregate has no ex-date per row.
"""
from __future__ import annotations

import argparse
import json

from scripts.twse_2021_22_traded_240_warmup_readonly import _private_file
from scripts.twse_2022_two_stock_action_coverage_readonly import (
    EVIDENCE_SCOPE as PRIOR_SCOPE,
)

SCOPE = "OWNER_OFFLINE_2022_TWSE_FROZEN2_KNOWN_DIVIDEND_GAP_EVIDENCE"
# Contemporary evidence of *event date*, not authoritative final
# adjustment factor nor PIT as-of source. Do not infer 2022/2023
# exact cash entitlement or build trading signals from it.
INDEPENDENTLY_REPORTED_EVENTS = {
    "2327": {
        "ex_date": "2022-07-04",
        "sources": [
            {
                "url": "https://www.cna.com.tw/news/afe/202207040027.aspx",
                "published_date": "2022-07-04",
                "description": "Contemporary actual ex-dividend-day news",
            },
            {
                "url": "https://www.cna.com.tw/news/afe/202206080024.aspx",
                "published_date": "2022-06-08",
                "description": "Contemporary company meeting announcement",
            },
        ],
        "money_amount_requires_reconciliation": True,
    },
    "2603": {
        "ex_date": "2022-06-29",
        "sources": [
            {
                "url": "https://www.cna.com.tw/news/afe/202205310431.aspx",
                "published_date": "2022-05-31",
                "description": "Contemporary company ex-date and payout announcement",
            },
            {
                "url": "https://www.cna.com.tw/news/afe/202206290418.aspx",
                "published_date": "2022-06-29",
                "description": "Contemporary actual ex-dividend-day news",
            },
        ],
        "money_amount_requires_reconciliation": True,
    },
}


def classify_historical_dividend_gaps(prior):
    if (not isinstance(prior, dict)
            or prior.get("schema_version") != 1
            or prior.get("scope") != PRIOR_SCOPE
            or prior.get("live_model_release_decision") != "BLOCKED"
            or prior.get("source_window_start") != "2021-12-30"
            or prior.get("source_window_end") != "2022-12-30"
            or prior.get("original_asof_issuer_publication_vintage_verified") is not False
            or prior.get("independently_complete_historical_dividends_and_splits") is not False
            or prior.get("cash_reduction_only_sma240_is_complete_total_return") is not False
            or type(prior.get("production_neon_writes")) is not int
            or prior["production_neon_writes"] != 0
            or type(prior.get("line_messages_sent")) is not int
            or prior["line_messages_sent"] != 0):
        raise ValueError("Requires exact accepted PR224 owner-private blocked evidence")

    rows = prior.get("per_stock_action_coverage")
    if (not isinstance(rows, list) or len(rows) != 2
            or type(prior.get("actual_readonly_stored_action_rows")) is not int
            or not 0 <= prior["actual_readonly_stored_action_rows"] <= 200):
        raise ValueError("Bounded two-stock recorded action summary missing")
    by_stock = {}
    total_rows = 0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Malformed prior stock action summary")
        sid = row.get("stock_id")
        keys = (
            "stored_event_rows_in_proven_240_traded_day_window",
            "stored_verified_event_rows",
            "stored_unverified_event_rows",
            "stored_cash_dividend_rows",
            "stored_cash_dividend_rows_missing_amount",
            "stored_non_cash_reduction_event_rows",
        )
        if (sid not in INDEPENDENTLY_REPORTED_EVENTS or sid in by_stock
                or any(type(row.get(k)) is not int or not 0 <= row[k] <= 200
                       for k in keys)
                or row["stored_verified_event_rows"] +
                   row["stored_unverified_event_rows"] != row[keys[0]]
                or row["stored_cash_dividend_rows"] > row[keys[0]]
                or row["stored_cash_dividend_rows_missing_amount"] >
                   row["stored_cash_dividend_rows"]
                or row["stored_non_cash_reduction_event_rows"] > row[keys[0]]
                or row.get("no_stored_event_means_no_real_dividend") is not False
                or row.get("full_corporate_action_and_dividend_history_verified") is not False):
            raise ValueError("Bad/incomplete/duplicated stock action evidence")
        by_stock[sid] = row
        total_rows += row[keys[0]]
    if (set(by_stock) != set(INDEPENDENTLY_REPORTED_EVENTS)
            or total_rows != prior["actual_readonly_stored_action_rows"]):
        raise ValueError("Previous live read-only totals do not reconcile")

    output = []
    for sid, evidence in sorted(INDEPENDENTLY_REPORTED_EVENTS.items()):
        n = by_stock[sid]["stored_cash_dividend_rows"]
        if n == 0:
            status = "CONFIRMED_MISSING_FROM_PRIOR_STORED_CASH_DIVIDEND_INVENTORY"
        else:
            status = "EXACT_EX_DATE_MATCH_UNPROVEN_NEEDS_TARGETED_READONLY_QUERY"
        output.append({
            "stock_id": sid,
            "known_historical_cash_dividend_ex_date": evidence["ex_date"],
            "prior_neon_stored_cash_dividend_rows_in_entire_window": n,
            "dated_event_vs_prior_neon_status": status,
            "contemporaneous_public_event_evidence": evidence["sources"],
            "precise_per_share_cash_amount_certified": False,
            "historically_complete_official_action_ledger_certified": False,
            "historical_ex_ante_publication_vintage_rebuilt": False,
            "historical_dividend_event_insert_permitted": False,
            "stock_price_factor_or_sma240_recomputed": False,
        })
    return {
        "schema_version": 1,
        "scope": SCOPE,
        "inherited_scope": PRIOR_SCOPE,
        "prior_owner_neon_stored_event_rows": total_rows,
        "independently_dated_2022_cash_dividend_events": len(output),
        "events_confirmed_missing_from_prior_neon_cash_dividend_inventory":
            sum(e["dated_event_vs_prior_neon_status"].startswith("CONFIRMED_MISSING")
                for e in output),
        "per_stock_known_dividend_event_gaps": output,
        "outside_data_does_not_prove_exhaustive_2022_action_universe": True,
        "historical_asof_issuer_membership_verified": False,
        "fully_adjusted_sma240_or_true_total_return_approved": False,
        "official_final_cash_amount_and_factor_still_require_validation": True,
        "production_neon_writes": 0,
        "line_messages_sent": 0,
        "paid_upgrade_requested": False,
        "live_model_release_decision": "BLOCKED",
    }


def main():
    p = argparse.ArgumentParser(
        description="Offline 2022 two-stock known cash dividend gaps, no DB call")
    p.add_argument("--prior-action-report", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    try:
        source = _private_file(args.prior_action_report, should_exist=True)
        target = _private_file(args.out, should_exist=False)
        if source == target:
            raise ValueError("Cannot overwrite previous owner report")
        prior = json.loads(source.read_text(encoding="utf-8"))
        proof = classify_historical_dividend_gaps(prior)
        with target.open("x", encoding="utf-8") as stream:
            json.dump(proof, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        print(json.dumps({
            "status": "TWO_STOCK_2022_KNOWN_DIVIDEND_GAP_OFFLINE_PASS",
            "dated_historical_cash_dividend_events":
                proof["independently_dated_2022_cash_dividend_events"],
            "confirmed_missing_from_prior_neon_cash_dividend_inventory":
                proof["events_confirmed_missing_from_prior_neon_cash_dividend_inventory"],
            "amounts_and_adjusted_total_returns_certified": False,
            "neon_writes": 0,
            "line_messages_sent": 0,
            "model_release": "BLOCKED",
        }, ensure_ascii=False))
    except Exception:
        raise SystemExit(
            "Owner-private dated-dividend gap evidence FAILED; no database "
            "access, PRICE changes, LINE, or secrets printed"
        ) from None


if __name__ == "__main__":
    main()
