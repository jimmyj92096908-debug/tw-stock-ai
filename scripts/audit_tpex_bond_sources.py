#!/usr/bin/env python3
"""Fetch TPEx official bond issue datasets and validate exact BondCode fields.

Read-only evidence audit only. No database writes and no quote downloads.
"""
from __future__ import annotations
import argparse, hashlib, json, time
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://www.tpex.org.tw/openapi/v1"
ROUTES = {
    "international_bond_issue_investor": ("tpex_international_bond_issue_investor", "BondCode"),
    "international_bond_issue_org": ("tpex_international_bond_issue_org", "BondCode"),
    "government_bond_issue": ("bond_ISSBD1_data", "BondCode"),
    "foreign_financial_bond_issue": ("bond_ISSBD2_data", "BondCode"),
    "financial_bond_issue": ("bond_ISSBD3_data", "BondCode"),
    "ordinary_bond_issue": ("bond_ISSBD4_data", "BondCode"),
    "convertible_bond_issue": ("bond_ISSBD5_data", "BondCode"),
    "overseas_convertible_bond_issue": ("bond_ISSBD6_data", "BondCode"),
    "warrant_bond_issue": ("bond_ISSBD7_data", "BondCode"),
    "overseas_warrant_bond_issue": ("bond_ISSBD8_data", "BondCode"),
    "overseas_ordinary_bond_issue": ("bond_ISSBD9_data", "BondCode"),
    "formosa_bond_domestic_issuer": ("bond_ISSBD10_data", "BondCode"),
    "formosa_bond_foreign_issuer": ("bond_ISSBD11_data", "BondCode"),
}

def inspect_rows(payload, code_field):
    if not isinstance(payload, list) or not payload:
        raise ValueError("expected non-empty JSON array")
    codes = []
    for i, row in enumerate(payload, 1):
        if not isinstance(row, dict):
            raise ValueError(f"row {i} is not an object")
        code = str(row.get(code_field) or "").strip()
        if not code:
            raise ValueError(f"row {i} missing {code_field}")
        codes.append(code)
    if len(codes) != len(set(codes)):
        raise ValueError(f"duplicate values in {code_field}")
    return codes

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="audit-output/market-scope/tpex-bonds")
    args = parser.parse_args()
    out = Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
    import requests
    results = {}
    all_codes = set()
    for source_id, (route, field) in ROUTES.items():
        url = f"{BASE_URL}/{route}"
        raw_path = out / f"{source_id}-raw.json"
        result = {"url": url, "route": route, "code_field": field,
                  "fetch_status": "unavailable", "schema_validated": False,
                  "source_row_count": 0, "security_code_count": 0,
                  "security_codes": [], "http_status": None, "content_type": "",
                  "bytes": 0, "sha256": None, "error": None}
        response = None
        for attempt in range(1, 4):
            try:
                response = requests.get(url, timeout=(10, 60),
                    headers={"User-Agent": "tw-stock-ai-tpex-bond-audit/1.0", "Accept": "application/json"})
                response.raise_for_status()
                break
            except requests.RequestException as exc:
                result["error"] = f"{type(exc).__name__}: {exc}"
                if attempt < 3:
                    time.sleep(attempt * 2)
        if response is not None:
            raw = response.content
            raw_path.write_bytes(raw)
            result.update({"http_status": response.status_code,
                "content_type": response.headers.get("Content-Type", ""),
                "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
            try:
                payload = json.loads(raw.decode("utf-8-sig"))
                codes = inspect_rows(payload, field)
                result.update({"fetch_status": "schema_validated", "schema_validated": True,
                    "source_row_count": len(payload), "security_code_count": len(codes),
                    "security_codes": codes, "error": None})
                all_codes.update(codes)
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                result["error"] = f"{type(exc).__name__}: {exc}"
                result["fetch_status"] = "schema_review_required"
        results[source_id] = result
    (out / "tpex-bond-codes-raw.json").write_text(\n        json.dumps([{"BondCode": code} for code in sorted(all_codes)], ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": BASE_URL, "source_count": len(results),
        "validated_source_count": sum(x["schema_validated"] for x in results.values()),
        "unavailable_source_count": sum(not x["schema_validated"] for x in results.values()),
        "unique_bond_code_count": len(all_codes), "unique_bond_codes": sorted(all_codes),
        "sources": results, "exact_code_field": "BondCode",
        "classification_confirmed": False, "automatic_exclusion_performed": False,
        "database_accessed": False, "database_modified": False,
        "five_year_quotes_downloaded": False, "quote_download_authorized": False,
    }
    (out / "tpex-bond-source-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "source_count", "validated_source_count", "unavailable_source_count",
        "unique_bond_code_count", "classification_confirmed", "database_modified",
        "five_year_quotes_downloaded")}, ensure_ascii=False, sort_keys=True))

if __name__ == "__main__":
    main()
