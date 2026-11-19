#!/usr/bin/env python3
"""Probe the TPEx ETF InfoHub's observed JSON data endpoint.

The endpoint is treated as a discovery candidate until its live response
passes transport and schema checks. Raw bytes are preserved. This script
does not independently classify securities, access a database, or download
quotations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

URL = "https://info.tpex.org.tw/api/etfFilter"
CODE_FIELD_NAMES = {"stockno", "securitycode", "security_code", "證券代號", "證券代碼", "股票代號", "股票代碼"}


def describe_payload(payload: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "root_type": type(payload).__name__,
        "record_count": 0,
        "record_fields": [],
        "security_code_field_candidates": [],
        "security_code_field": None,
        "security_code_count": 0,
        "security_codes": [],
        "duplicate_security_code_count": 0,
        "schema_validated": False,
    }
    rows: list[dict[str, Any]] = []
    if isinstance(payload, list):
        rows = [x for x in payload if isinstance(x, dict)]
    elif isinstance(payload, dict):
        result["root_keys"] = sorted(str(k) for k in payload.keys())
        # Prefer the actual ETF records over auxiliary lists such as factorList.
        preferred = ("data", "list", "items", "records")
        keys = [k for k in preferred if k in payload]
        keys += [k for k in payload if k not in keys]
        for key in keys:
            value = payload[key]
            if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
                rows = value
                result["records_container_key"] = str(key)
                break
    result["record_count"] = len(rows)
    if rows:
        fields = sorted({str(k) for row in rows for k in row})
        result["record_fields"] = fields
        candidates = [
            field for field in fields
            if field.replace("_", "").lower() in CODE_FIELD_NAMES
            or any(token in field.lower() for token in ("代號", "代碼", "securitycode"))
        ]
        result["security_code_field_candidates"] = candidates
        result["schema_validated"] = bool(fields)
        if len(candidates) == 1:
            field = candidates[0]
            codes = [str(row.get(field, "")).strip() for row in rows]
            codes = [code for code in codes if code]
            result["security_code_field"] = field
            result["security_code_count"] = len(codes)
            result["security_codes"] = sorted(set(codes))
            result["duplicate_security_code_count"] = len(codes) - len(set(codes))
            result["exact_security_code_field_confirmed"] = bool(codes) and result["duplicate_security_code_count"] == 0
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="audit-output/market-scope/tpex-etf")
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    import requests

    response = requests.get(
        URL, timeout=(8, 45),
        headers={"User-Agent": "tw-stock-ai-etf-source-audit/1.0", "Accept": "application/json"},
    )
    raw = response.content
    (output / "tpex-etf-infohub-raw.json").write_bytes(raw)
    try:
        response.raise_for_status()
        payload = json.loads(raw.decode("utf-8-sig"))
        inspected = describe_payload(payload)
        parse_error = None
    except (requests.RequestException, UnicodeDecodeError, json.JSONDecodeError) as exc:
        inspected = {"root_type": None, "record_count": 0, "record_fields": [],
                     "security_code_field_candidates": [], "security_code_field": None,
                     "security_code_count": 0, "security_codes": [],
                     "duplicate_security_code_count": 0, "schema_validated": False,
                     "exact_security_code_field_confirmed": False}
        parse_error = str(exc)

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_id": "tpex_etf_infohub_runtime_api_candidate",
        "url": URL,
        "source_page": "https://info.tpex.org.tw/ETF/zh/filter.html",
        "http_status": response.status_code,
        "content_type": response.headers.get("Content-Type", ""),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "parse_error": parse_error,
        **inspected,
        "classification_confirmed": False,
        "automatic_exclusion_performed": False,
        "database_accessed": False,
        "database_modified": False,
        "five_year_quotes_downloaded": False,
        "quote_download_authorized": False,
    }
    (output / "tpex-etf-infohub-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8"
    )
    print(json.dumps({
        "http_status": report["http_status"],
        "content_type": report["content_type"],
        "record_count": report["record_count"],
        "records_container_key": report.get("records_container_key"),
        "security_code_field": report["security_code_field"],
        "security_code_count": report["security_code_count"],
        "duplicate_security_code_count": report["duplicate_security_code_count"],
        "schema_validated": report["schema_validated"],
        "classification_confirmed": False,
        "database_modified": False,
        "five_year_quotes_downloaded": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
