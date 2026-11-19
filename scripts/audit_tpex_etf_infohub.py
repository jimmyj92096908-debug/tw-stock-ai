#!/usr/bin/env python3
"""Probe the TPEx ETF InfoHub's observed JSON data endpoint.

The endpoint is treated as an unverified discovery candidate until the live
response passes transport and schema checks. This script preserves raw bytes
and never classifies securities, accesses a database, or downloads quotations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

URL = "https://info.tpex.org.tw/api/etfFilter"


def describe_payload(payload: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "root_type": type(payload).__name__,
        "record_count": 0,
        "record_fields": [],
        "security_code_field_candidates": [],
        "schema_validated": False,
    }
    rows: list[dict[str, Any]] = []
    if isinstance(payload, list):
        rows = [x for x in payload if isinstance(x, dict)]
    elif isinstance(payload, dict):
        result["root_keys"] = sorted(str(k) for k in payload.keys())
        for key, value in payload.items():
            if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
                rows = value
                result["records_container_key"] = str(key)
                break
    result["record_count"] = len(rows)
    if rows:
        fields = sorted({str(k) for row in rows for k in row})
        result["record_fields"] = fields
        result["security_code_field_candidates"] = [
            field for field in fields
            if any(token in field.lower() for token in ("代號", "代碼", "code", "security"))
        ]
        result["schema_validated"] = bool(fields)
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
                     "security_code_field_candidates": [], "schema_validated": False}
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
        "exact_security_code_field_confirmed": False,
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
        "record_fields": report["record_fields"],
        "schema_validated": report["schema_validated"],
        "database_modified": False,
        "five_year_quotes_downloaded": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
