#!/usr/bin/env python3
"""Conservative, review-only analysis of a TDCC current securities master.

This produces candidate groups, not a historical trading universe. It does not
infer instrument type from codes/names, generate dates, or modify databases.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

MARKET_BUCKETS = {
    "上市": "listed_candidate",
    "上櫃": "otc_candidate",
    "興櫃": "emerging_candidate_separate",
    "未上市櫃": "unlisted_out_of_scope",
    "終止上市櫃": "terminated_out_of_scope",
}


def analyze_rows(rows: list[dict[str, str]]) -> dict[str, Any]:
    market_counts = Counter()
    status_counts = Counter()
    market_status_counts = Counter()
    buckets = Counter()
    candidate_rows: list[dict[str, str]] = []
    emerging_rows: list[dict[str, str]] = []
    unknown_rows: list[dict[str, str]] = []
    for row in rows:
        market = (row.get("市場別") or "").strip()
        status = (row.get("證券狀態") or "").strip()
        code = (row.get("證券代號") or "").strip()
        name = (row.get("證券名稱") or "").strip()
        market_counts[market or "(blank)"] += 1
        status_counts[status or "(blank)"] += 1
        market_status_counts[f"{market or '(blank)'} | {status or '(blank)'}"] += 1
        bucket = MARKET_BUCKETS.get(market, "unknown_market_review")\n        if market in ("上市", "上櫃") and status != "正常":\n            bucket = "listed_otc_inactive_or_nonstandard_status_review"
        if market in ("上市", "上櫃") and status == "正常":
            candidate_rows.append({"stock_id": code, "name": name, "market": market, "status": status})
            buckets["current_listed_otc_active_candidates"] += 1
        elif market == "興櫃" and status == "正常":
            emerging_rows.append({"stock_id": code, "name": name, "market": market, "status": status})
            buckets["emerging_active_separate_candidates"] += 1
        else:
            buckets[bucket] += 1
            if bucket == "unknown_market_review":
                unknown_rows.append({"stock_id": code, "name": name, "market": market, "status": status})
    return {
        "schema_version": 1,
        "source_scope": "TDCC current securities master; reference snapshot only",
        "row_count": len(rows),
        "market_counts": dict(sorted(market_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "market_status_counts": dict(sorted(market_status_counts.items())),
        "scope_bucket_counts": dict(sorted(buckets.items())),
        "current_listed_otc_active_candidate_count": len(candidate_rows),
        "current_listed_otc_active_candidates": candidate_rows,
        "emerging_active_candidate_count": len(emerging_rows),
        "emerging_active_candidates": emerging_rows,
        "unknown_market_review_count": len(unknown_rows),
        "unknown_market_review_rows": unknown_rows,
        "historical_universe_accepted": False,
        "trading_universe_accepted": False,
        "quote_download_authorized": False,
        "limitations": [
            "This is a current reference snapshot, not a date-effective historical universe.",
            "Listed and OTC active candidates may include ETFs, preferred shares, warrants, bonds, and other instruments; this analyzer does not classify instrument type.",
            "Emerging securities are kept separate pending endpoint coverage validation.",
            "Terminated, unlisted, and inactive records are not current candidates but may be needed for historical dates.",
            "No database access or changes are performed.",
        ],
    }


def analyze_csv(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"證券代號", "證券名稱", "市場別", "證券狀態"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"Missing required TDCC columns: {sorted(required)}")
        return analyze_rows(list(reader))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--candidates-csv", required=True)
    args = parser.parse_args()
    report = analyze_csv(Path(args.input))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    candidate_path = Path(args.candidates_csv)
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    with candidate_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["stock_id", "name", "market", "status"])
        writer.writeheader()
        writer.writerows(report["current_listed_otc_active_candidates"])
    print(json.dumps({
        "row_count": report["row_count"],
        "candidate_count": report["current_listed_otc_active_candidate_count"],
        "emerging_separate_count": report["emerging_active_candidate_count"],
        "historical_universe_accepted": False,
        "trading_universe_accepted": False,
        "output": str(output),
        "candidate_csv": str(candidate_path),
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
