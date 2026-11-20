"""Fail-closed reconciliation of two *read-only* indicator backlog snapshots.

Executed AFTER the bounded write job, never performs a database write itself.
A green scheduled workflow must prove indicator coverage increased rather than
only proving a Python command returned exit code 0. Counts may be affected by
other writers; do not confuse this aggregate check with stock-level proof.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


MARKETS = ("twse", "tpex")


def _markets(evidence):
    if (evidence.get("database_transaction_read_only") is not True
            or evidence.get("indicator_writes_performed") is not False
            or evidence.get("automatic_write_schedule_activated") is not False
            or evidence.get("candidate_selection_tested_against_real_sql") is not True):
        raise ValueError("Input is not an accepted read-only indicator snapshot")
    if evidence.get("schema_version") != 1:
        raise ValueError("Unknown probe schema")
    markets = {}
    for x in evidence.get("markets", ()):
        market = x.get("market")
        if market not in MARKETS or market in markets:
            raise ValueError("Invalid or duplicate market snapshot")
        values = {}
        for metric in ("eligible", "pending", "complete", "unstarted", "preview_candidate_count"):
            v = x.get(metric)
            if type(v) is not int or v < 0:
                raise ValueError("Invalid market metric")
            values[metric] = v
        if (values["pending"] + values["complete"] != values["eligible"]
                or values["unstarted"] > values["pending"]
                or values["preview_candidate_count"] != min(20, values["pending"])):
            raise ValueError("Inconsistent market metrics")
        markets[market] = values
    if set(markets) != set(MARKETS):
        raise ValueError("Both TWSE and TPEx evidence required")
    return markets


def reconcile(before, after):
    old, new = _markets(before), _markets(after)
    if not before.get("latest_price_date") or (
            before.get("latest_price_date") != after.get("latest_price_date")):
        raise ValueError("Price date changed during batch; retry proof on stable data")
    results = []
    problems = []
    for market in MARKETS:
        a, b = old[market], new[market]
        delta = a["pending"] - b["pending"]
        improved = b["complete"] - a["complete"]
        if b["eligible"] != a["eligible"]:
            status = "inconclusive_eligible_universe_changed"
            problems.append(market)
        elif a["pending"] == 0 and b["pending"] == 0:
            status = "no_work"
        elif delta > 0 and improved == delta:
            status = "improved"
        else:
            status = "no_proven_progress"
            problems.append(market)
        results.append({
            "market": market,
            "eligible_before": a["eligible"],
            "eligible_after": b["eligible"],
            "pending_before": a["pending"],
            "pending_after": b["pending"],
            "complete_before": a["complete"],
            "complete_after": b["complete"],
            "decrease_in_pending": delta,
            "status": status,
        })
    return {
        "schema_version": 1,
        "price_date": before["latest_price_date"],
        "markets": results,
        "progress_verified": not problems,
        "all_pending_cleared": all(x["pending_after"] == 0 for x in results),
        "failed_market_count": len(problems),
        "live_trade_signals_enabled": False,
        "line_webhook_changed": False,
        "caveat": "Aggregate stock coverage can also change due to concurrent writers; investigate run-level evidence.",
    }


def main():
    parser = argparse.ArgumentParser(description="Compare real indicator before/after read-only evidence")
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    before = json.loads(args.before.read_text(encoding="utf-8"))
    after = json.loads(args.after.read_text(encoding="utf-8"))
    result = reconcile(before, after)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for x in result["markets"]:
        print(f"{x['market']}: {x['pending_before']} -> {x['pending_after']} pending ({x['status']})")
    if not result["progress_verified"]:
        raise SystemExit("Cannot confirm bounded indicator backfill progress; downstream scoring blocked")


if __name__ == "__main__":
    main()
