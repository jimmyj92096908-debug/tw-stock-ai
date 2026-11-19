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
from urllib.parse import parse_qs, urlsplit


SOURCE_SPECS = {
    "twse_warrants": ("instrument-sources/twse_warrants-raw.json", "權證代號", "TWSE", "warrant"),
    "twse_fund_basic": ("instrument-sources/twse_fund_basic-raw.json", "基金代號", "TWSE", "fund_or_etf"),
    "tpex_warrants": ("instrument-sources/tpex_warrants-raw.json", "權證代號", "TPEX", "warrant"),
    "tpex_etf": ("tpex-etf/tpex-etf-infohub-raw.json", "stockNo", "TPEX", "etf"),
    "tpex_bonds": ("tpex-bonds/tpex-bond-codes-raw.json", "BondCode", "TPEX", "bond"),
    "tpex_etn_current": ("tpex-etn-query-discovery/current_listing_api_response.json", "證券代號", "TPEX", "etn"),
}


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


def load_tpex_etn_table_codes(path: Path, field: str) -> set[str]:
    """Validate TPEx's nested table and its optional per-row detail-link column.

    The official response declares six table fields but currently appends a
    seventh detail URL to each data row. Accept that extra value only when it
    is a detail.html link whose query contains exactly one type and one code,
    and the linked code exactly equals the row's declared security code.
    """
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected JSON object")
    tables = payload.get("tables")
    if not isinstance(tables, list) or len(tables) != 1 or not isinstance(tables[0], dict):
        raise ValueError(f"{path}: expected exactly one table object")
    table = tables[0]
    fields = table.get("fields")
    rows = table.get("data")
    if not isinstance(fields, list) or fields.count(field) != 1:
        raise ValueError(f"{path}: expected exactly one {field!r} column")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{path}: expected non-empty table data")
    index = fields.index(field)
    expected_width = len(fields)
    observed_widths = {len(row) for row in rows if isinstance(row, list)}
    if any(not isinstance(row, list) for row in rows):
        raise ValueError(f"{path}: every table row must be an array")
    if len(observed_widths) != 1 or not observed_widths.issubset({expected_width, expected_width + 1}):
        raise ValueError(f"{path}: inconsistent or unsupported table row widths")
    has_detail_link = observed_widths == {expected_width + 1}
    codes = []
    for row_number, row in enumerate(rows, start=1):
        if len(row) != expected_width + (1 if has_detail_link else 0):
            raise ValueError(f"{path}: row {row_number} width does not match validated table shape")
        code = str(row[index] or "").strip()
        if not code:
            raise ValueError(f"{path}: missing {field!r} at row {row_number}")
        if has_detail_link:
            detail_url = str(row[expected_width] or "").strip()
            parsed = urlsplit(detail_url)
            query = parse_qs(parsed.query, keep_blank_values=True)
            if (
                parsed.path != "detail.html"
                or set(query) != {"type", "code"}
                or len(query["type"]) != 1
                or not query["type"][0]
                or len(query["code"]) != 1
                or query["code"][0] != code
            ):
                raise ValueError(
                    f"{path}: row {row_number} detail link is invalid or does not match its security code"
                )
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


def write_audit_csv(records: list[dict[str, Any]], output_path: Path) -> None:
    """Write all exclusion records, including operator-directed reasons, to CSV."""
    fields = [
        "stock_id", "name", "market", "bucket",
        "instrument_subtype_confirmed", "exclusion_evidence",
        "manual_exclusion_reason",
    ]
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        for row in records:
            csv_row = {
                **row,
                "exclusion_evidence": json.dumps(row["exclusion_evidence"], ensure_ascii=False),
            }
            writer.writerow(csv_row)


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
        source_sha256 = sha256_file(path)
        try:
            if source_id == "tpex_etn_current":
                codes = load_tpex_etn_table_codes(path, field)
            else:
                container = "data" if source_id == "tpex_etf" else None
                codes = load_codes(path, field, container)
            schema_validated = True
            source_error = None
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            codes = set()
            schema_validated = False
            source_error = f"{type(exc).__name__}: {exc}"
        source_codes[source_id] = {
            "market": market, "category": category, "codes": codes,
            "path": str(path), "sha256": source_sha256, "code_field": field,
            "schema_validated": schema_validated, "source_error": source_error,
            "coverage_status": "current_snapshot" if source_id == "tpex_etn_current" else "audited_feed",
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
        "classification_coverage_complete": all(item["schema_validated"] for item in source_codes.values()),
        "historical_lifecycle_coverage_complete": False,
    }
    report["sources"] = {
        source_id: {
            "market": item["market"], "category": item["category"],
            "code_field": item["code_field"], "code_count": len(item["codes"]),
            "schema_validated": item["schema_validated"],
            "source_error": item["source_error"],
            "coverage_status": item["coverage_status"],
            "sha256": item["sha256"],
        } for source_id, item in source_codes.items()
    }

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "exact-instrument-exclusion-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_audit_csv(report["records"], output / "exact-instrument-exclusion-audit.csv")
    etn_source = report["sources"]["tpex_etn_current"]
    etn_exact_match_codes = sorted(
        row["stock_id"]
        for row in report["records"]
        if any(
            evidence["source_id"] == "tpex_etn_current"
            for evidence in row.get("exclusion_evidence", [])
        )
    )
    print(json.dumps({
        "record_count": report["record_count"],
        "review_record_count": report["review_record_count"],
        "bucket_counts": report["bucket_counts"],
        "tpex_etn_current": {
            "schema_validated": etn_source["schema_validated"],
            "code_count": etn_source["code_count"],
            "source_error": etn_source["source_error"],
            "exact_match_candidate_codes": etn_exact_match_codes,
        },
        "common_stock_classification_confirmed": False,
        "database_modified": False,
        "five_year_quotes_downloaded": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
