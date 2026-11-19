#!/usr/bin/env python3
"""Match exchange candidates against exact-code official non-common instruments.

Only exact identifier matches are excluded. A non-match is not proof that a
record is an ordinary common stock; unresolved records remain candidates with
instrument subtype pending.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


SOURCE_SPECS = {
    "twse_warrants": ("instrument-sources/twse_warrants-raw.json", "權證代號", "TWSE", "warrant"),
    "twse_fund_basic": ("instrument-sources/twse_fund_basic-raw.json", "基金代號", "TWSE", "fund_or_etf"),
    "tpex_warrants": ("instrument-sources/tpex_warrants-raw.json", "權證代號", "TPEX", "warrant"),
    "tpex_etf": ("tpex-etf/tpex-etf-infohub-raw.json", "stockNo", "TPEX", "etf"),
    "tpex_bonds": ("tpex-bonds/tpex-bond-codes-raw.json", "BondCode", "TPEX", "bond"),
    "tpex_etn_partial": ("tpex-etn/tpex-etn-codes-raw.json", "security_code", "TPEX", "etn"),
}

PARTIAL_COVERAGE_SOURCES = {"tpex_etn_partial"}

# The ETN source is an official current ESG showcase page, not a complete ETN master.


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_codes(path: Path, field: str, container: str | None = None) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if container:
        if not isinstance(payload, dict):
            raise ValueError(f"{path}: expected JSON object with {container!r}")
        payload = payload.get(container)
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"{path}: expected non-empty record list")
    codes = []
    for index, row in enumerate(payload, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: row {index} is not an object")
        code = str(row.get(field) or "").strip()
        if not code:
            raise ValueError(f"{path}: missing {field!r} at row {index}")
        codes.append(code)
    if len(codes) != len(set(codes)):
        raise ValueError(f"{path}: duplicate values in {field!r}")
    return set(codes)


def reconcile_exact_codes(
    exchange_rows: list[dict[str, str]],
    source_codes: dict[str, dict[str, Any]],
    manual_exclusion_records: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    records = []
    seen: set[str] = set()
    for row in exchange_rows:
        code = str(row.get("stock_id", "")).strip()
        if not code:
            raise ValueError("Exchange candidate has an empty stock_id")
        if code in seen:
            raise ValueError(f"Duplicate exchange candidate code: {code}")
        seen.add(code)
        matches = [
            {"source_id": source_id, "market": item["market"], "category": item["category"]}
            for source_id, item in source_codes.items()
            if code in item["codes"]
        ]
        records.append({
            "stock_id": code,
            "name": row.get("name", ""),
            "market": row.get("market", ""),
            "bucket": "excluded" if matches else "candidate",
            "instrument_subtype_confirmed": False,
            "exclusion_evidence": matches,
        })
    for row in manual_exclusion_records or []:
        code = str(row.get("stock_id", "")).strip()
        if not code or code in seen:
            raise ValueError(f"Invalid or duplicate manual exclusion code: {code!r}")
        seen.add(code)
        records.append({
            "stock_id": code, "name": row.get("name", ""),
            "market": row.get("market", ""), "bucket": "excluded",
            "instrument_subtype_confirmed": False, "exclusion_evidence": [],
            "manual_exclusion_reason": row.get("review_reason", "operator-directed exclusion"),
        })
    counts = {bucket: sum(r["bucket"] == bucket for r in records)
              for bucket in ("candidate", "excluded")}
    return {
        "schema_version": 1,
        "matching_rule": "exact stock_id equality only; no name or code-pattern inference",
        "record_count": len(records),
        "bucket_counts": counts,
        "records": records,
        "interpretation": [
            "Excluded means an exact security-code match exists in an audited official non-common-instrument source.",
            "Candidate means no exact match was found in the sources audited here; it does not prove ordinary common-stock subtype.",
            "Uncovered instrument categories and incomplete official feeds remain unresolved and must not be treated as cleared.",
        ],
        "common_stock_classification_confirmed": False,
        "historical_universe_accepted": False,
        "quote_download_authorized": False,
        "database_accessed": False,
        "database_modified": False,
        "five_year_quotes_downloaded": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-root", required=True)
    parser.add_argument("--reconciliation-json", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    root = Path(args.audit_root)
    source_codes: dict[str, dict[str, Any]] = {}
    for source_id, (relative_path, field, market, category) in SOURCE_SPECS.items():
        path = root / relative_path
        container = "data" if source_id == "tpex_etf" else None
        source_sha256 = sha256_file(path)
        try:
            codes = load_codes(path, field, container)
            schema_validated = True
            source_error = None
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            # Invalid/HTML response is unavailable evidence, not an empty list.
            # Fail closed: no exclusion can be based on this source.
            codes = set()
            schema_validated = False
            source_error = f"{type(exc).__name__}: {exc}"
        source_codes[source_id] = {
            "market": market, "category": category, "codes": codes,
            "path": str(path), "sha256": source_sha256, "code_field": field,
            "schema_validated": schema_validated, "source_error": source_error,
            "coverage_status": "partial" if source_id in PARTIAL_COVERAGE_SOURCES else "audited_feed",
        }

    reconciliation = json.loads(Path(args.reconciliation_json).read_text(encoding="utf-8-sig"))
    all_records = reconciliation.get("records", [])
    if not isinstance(all_records, list):
        raise ValueError("Reconciliation JSON must contain a records array")
    exchange_rows = [row for row in all_records if row.get("bucket") == "candidate"]
    review_records = [row for row in all_records if row.get("bucket") == "review"]
    manual_exclusion_records = [row for row in all_records if row.get("bucket") == "excluded"]
    report = reconcile_exact_codes(exchange_rows, source_codes, manual_exclusion_records)
    report["manual_exclusion_count"] = len(manual_exclusion_records)
    report["manual_exclusion_records"] = manual_exclusion_records
    report["review_record_count"] = len(review_records)
    report["review_records"] = review_records
    report["coverage"] = {
        "unavailable_source_count": sum(not item["schema_validated"] for item in source_codes.values()),
        "partial_source_count": sum(item["coverage_status"] == "partial" for item in source_codes.values()),
        "classification_coverage_complete": all(item["schema_validated"] and item["coverage_status"] != "partial" for item in source_codes.values()),
    }
    report["sources"] = {
        source_id: {
            "market": item["market"], "category": item["category"],
            "code_field": item["code_field"], "code_count": len(item["codes"]),
            "schema_validated": item["schema_validated"],
            "source_error": item["source_error"],
            "sha256": item["sha256"],
        } for source_id, item in source_codes.items()
    }

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "exact-instrument-exclusion-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (output / "exact-instrument-exclusion-audit.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        fields = ["stock_id", "name", "market", "bucket", "instrument_subtype_confirmed", "exclusion_evidence"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in report["records"]:
            writer.writerow({**row, "exclusion_evidence": json.dumps(row["exclusion_evidence"], ensure_ascii=False)})
    print(json.dumps({
        "record_count": report["record_count"],
        "review_record_count": report["review_record_count"],
        "bucket_counts": report["bucket_counts"],
        "common_stock_classification_confirmed": False,
        "database_modified": False,
        "five_year_quotes_downloaded": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
