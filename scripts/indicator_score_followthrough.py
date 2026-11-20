"""Validate that a verified indicator batch flows through to valid scores.

Pure comparison of read-only Neon audits. This does not write, place orders
or infer investment profitability from stock coverage.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

def assess(before: dict, after: dict, indicator_proof: dict) -> dict:
    if not indicator_proof.get("progress_verified") or indicator_proof.get("live_trade_signals_enabled") is not False:
        raise ValueError("An independently verified indicator batch is required")
    if not indicator_proof.get("markets") or indicator_proof.get("schema_version") != 1:
        raise ValueError("Missing verified indicator market evidence")
    bdate = before["latest"]["latest_price_date"]
    adate = after["latest"]["latest_price_date"]
    scored_b = before["latest"]["latest_score_date"]
    scored_a = after["latest"]["latest_score_date"]
    if not bdate or bdate != adate or indicator_proof.get("price_date") != adate:
        raise ValueError("Daily price date changed across score refresh")
    if scored_a != adate:
        raise ValueError("Newest valid composite score is stale against latest price date")
    b = int(before["analysis_readiness"]["scored_stocks"])
    a = int(after["analysis_readiness"]["scored_stocks"])
    latest_b = int(before["analysis_readiness"]["scored_latest_price_day"])
    latest_a = int(after["analysis_readiness"]["scored_latest_price_day"])
    if min(a, b, latest_a, latest_b) < 0 or a < b or latest_a < latest_b:
        raise ValueError("Valid composite coverage unexpectedly decreased")
    pending_reduced = sum(max(0, int(x["decrease_in_pending"])) for x in indicator_proof["markets"])
    if pending_reduced > 0 and (a == b or latest_a == latest_b):
        raise ValueError("Newly completed indicator stocks did not increase valid score coverage")
    return {
        "schema_version": 1,
        "trade_date": adate,
        "valid_scored_before": b,
        "valid_scored_after": a,
        "valid_scored_added": a - b,
        "latest_trade_day_scored_before": latest_b,
        "latest_trade_day_scored_after": latest_a,
        "indicator_stocks_newly_completed": pending_reduced,
        "completed_indicator_to_score_research_pipeline": True,
        "no_trade_signals_approved": True,
    }

def main():
    parser = argparse.ArgumentParser(description="Read-only indicator-to-score followthrough evidence")
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--indicator", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    data = assess(
        json.loads(args.before.read_text(encoding="utf-8")),
        json.loads(args.after.read_text(encoding="utf-8")),
        json.loads(args.indicator.read_text(encoding="utf-8")),
    )
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Valid composite coverage: {data['valid_scored_before']} -> {data['valid_scored_after']}; "
          f"latest trade day: {data['latest_trade_day_scored_before']} -> {data['latest_trade_day_scored_after']}")
    print("Research-only score followthrough verified; trading remains disabled.")

if __name__ == "__main__":
    main()
