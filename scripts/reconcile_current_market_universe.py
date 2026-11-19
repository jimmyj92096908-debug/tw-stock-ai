#!/usr/bin/env python3
"""Reconcile current TWSE/TPEx company snapshots against the TDCC master.

This is a read-only evidence audit. It does not decide instrument subtype,
accept the historical universe, authorize quote downloads, or access a database.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reconcile_records(
    twse_rows: list[dict[str, str]],
    tpex_rows: list[dict[str, str]],
    tdcc_rows: list[dict[str, str]],
    tdcc_active_candidate_rows: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    exchange_rows = [*twse_rows, *tpex_rows]
    exchange_by_code: dict[str, list[dict[str, str]]] = defaultdict(list)
    tdcc_by_code: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in exchange_rows:
        exchange_by_code[str(row.get("stock_id", "")).strip()].append(row)
    for row in tdcc_rows:
        tdcc_by_code[str(row.get("證券代號", "")).strip()].append(row)

    reconciled: list[dict[str, Any]] = []
    for code in sorted(exchange_by_code):
        sources = exchange_by_code[code]
        if not code:
            continue
        if len(sources) != 1:
            source = sources[0]
            reconciled.append({
                "stock_id": code, "name": source.get("name", ""),
                "market": source.get("market", ""), "tdcc_market": "",
                "tdcc_status": "", "bucket": "review",
                "review_reason": "duplicate_code_across_exchange_sources",
                "listing_date_raw": source.get("listing_date_raw", ""),
            })
            continue

        source = sources[0]
        tdcc_matches = tdcc_by_code.get(code, [])
        reason = ""
        tdcc_market = tdcc_matches[0].get("市場別", "") if len(tdcc_matches) == 1 else ""
        tdcc_status = tdcc_matches[0].get("證券狀態", "") if len(tdcc_matches) == 1 else ""
        expected_market = {"TWSE": "上市", "TPEX": "上櫃"}.get(source.get("market", ""))

        if not tdcc_matches:
            bucket, reason = "review", "missing_in_tdcc_master"
        elif len(tdcc_matches) > 1:
            bucket, reason = "review", "duplicate_code_in_tdcc_master"
        elif tdcc_status != "正常":
            bucket, reason = "review", "tdcc_status_conflicts_with_current_exchange_snapshot"
        elif tdcc_market != expected_market:
            bucket, reason = "review", "tdcc_market_conflicts_with_exchange_snapshot"
        else:
            bucket, reason = "candidate", "active_market_match_in_tdcc_pending_instrument_subtype"

        reconciled.append({
            "stock_id": code,
            "name": source.get("name", ""),
            "market": source.get("market", ""),
            "tdcc_market": tdcc_market,
            "tdcc_status": tdcc_status,
            "bucket": bucket,
            "review_reason": reason,
            "listing_date_raw": source.get("listing_date_raw", ""),
        })

    exchange_codes = set(exchange_by_code)
    tdcc_only_count = 0
    tdcc_only_samples = []
    for row in tdcc_active_candidate_rows or []:
        code = str(row.get("stock_id", "")).strip()
        if code and code not in exchange_codes:
            tdcc_only_count += 1
            if len(tdcc_only_samples) < 25:
                tdcc_only_samples.append({
                    "stock_id": code,
                    "name": row.get("name", ""),
                    "market": row.get("market", ""),
                    "status": row.get("status", ""),
                })

    counts = defaultdict(int)
    for row in reconciled:
        counts[row["bucket"]] += 1

    return {
        "schema_version": 1,
        "scope": "current TWSE/TPEx company snapshots cross-checked against TDCC",
        "record_count": len(reconciled),
        "bucket_counts": {
            "candidate": counts["candidate"],
            "review": counts["review"],
            "excluded": 0,
        },
        "tdcc_active_instruments_not_in_exchange_company_snapshots_count": tdcc_only_count,
        "tdcc_only_samples": tdcc_only_samples,
        "records": reconciled,
        "interpretation": [
            "Candidate means the exchange snapshot and TDCC market/status fields agree; it is not confirmation of common-stock instrument subtype.",
            "Review records have missing or conflicting cross-source evidence and must not be silently included or excluded.",
            "TDCC-only active instruments are not automatically classified as ETFs, bonds, warrants, or common stocks by this report.",
            "No records are placed in the final excluded bucket because the available source fields do not establish instrument subtype.",
        ],
        "historical_universe_accepted": False,
        "common_stock_classification_confirmed": False,
        "quote_download_authorized": False,
        "database_accessed": False,
        "database_modified": False,
        "five_year_quotes_downloaded": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--twse-csv", required=True)
    parser.add_argument("--tpex-csv", required=True)
    parser.add_argument("--tdcc-master-csv", required=True)
    parser.add_argument("--tdcc-active-candidates-csv", required=True)
    parser.add_argument("--twse-audit-json", required=True)
    parser.add_argument("--tpex-audit-json", required=True)
    parser.add_argument("--output-dir", default="audit-output/market-scope/reconciliation")
    args = parser.parse_args()

    twse_rows = read_csv(args.twse_csv)
    tpex_rows = read_csv(args.tpex_csv)
    tdcc_rows = read_csv(args.tdcc_master_csv)
    tdcc_active_rows = read_csv(args.tdcc_active_candidates_csv)
    report = reconcile_records(twse_rows, tpex_rows, tdcc_rows, tdcc_active_rows)
    report["generated_at_utc"] = (
        read_json(args.twse_audit_json).get("generated_at_utc")
    )
    report["source_evidence"] = {
        "twse": {
            "url": read_json(args.twse_audit_json).get("url"),
            "sha256": read_json(args.twse_audit_json).get("sha256"),
            "candidate_count": len(twse_rows),
        },
        "tpex": {
            "url": read_json(args.tpex_audit_json).get("url"),
            "sha256": read_json(args.tpex_audit_json).get("sha256"),
            "candidate_count": len(tpex_rows),
        },
        "tdcc_master_sha256": sha256_file(args.tdcc_master_csv),
    }

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "current-market-universe-reconciliation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (output / "current-market-universe-reconciliation.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        fields = [
            "stock_id", "name", "market", "tdcc_market", "tdcc_status",
            "bucket", "review_reason", "listing_date_raw",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(report["records"])

    print(json.dumps({
        "record_count": report["record_count"],
        "bucket_counts": report["bucket_counts"],
        "tdcc_only_count": report["tdcc_active_instruments_not_in_exchange_company_snapshots_count"],
        "common_stock_classification_confirmed": False,
        "database_modified": False,
        "five_year_quotes_downloaded": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
