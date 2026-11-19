#!/usr/bin/env python3
"""Fetch official TWSE/TPEx instrument-class datasets and preserve raw evidence.

This stage is deliberately schema-discovery only: it never changes the stock
universe. A dataset is eligible for exact-code matching only when exactly one
recognized security-code field is present and every usable row has a code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SOURCES = {
    "twse_warrants": {
        "url": "https://openapi.twse.com.tw/v1/opendata/t187ap37_L",
        "market": "TWSE",
        "category": "warrant",
    },
    "twse_fund_basic": {
        "url": "https://openapi.twse.com.tw/v1/opendata/t187ap47_L",
        "market": "TWSE",
        "category": "fund_or_etf",
    },
    "tpex_warrants": {
        "url": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap37_O",
        "market": "TPEX",
        "category": "warrant",
    },
}

CODE_FIELDS = (
    "證券代號", "有價證券代號", "權證代號", "股票代號",
    "代號", "基金代號", "SecuritiesCompanyCode", "SecurityCode", "Code", "code",
)


def inspect_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, list) or not payload:
        raise ValueError("Expected a non-empty JSON array")
    if not all(isinstance(row, dict) for row in payload):
        raise ValueError("Every source row must be a JSON object")
    fields = sorted({str(key) for row in payload for key in row})
    code_fields = [field for field in CODE_FIELDS if field in fields]
    if len(code_fields) != 1:
        raise ValueError(
            "Could not identify exactly one recognized security-code field; "
            f"recognized={code_fields}, available_fields={fields}"
        )
    code_field = code_fields[0]
    codes: list[str] = []
    missing_rows = []
    seen = set()
    for index, row in enumerate(payload, start=1):
        value = str(row.get(code_field) or "").strip()
        if not value:
            missing_rows.append(index)
            continue
        if value in seen:
            raise ValueError(f"Duplicate security code {value!r} at row {index}")
        seen.add(value)
        codes.append(value)
    if missing_rows:
        raise ValueError(
            f"Missing security codes in {len(missing_rows)} rows; "
            f"first_rows={missing_rows[:10]}"
        )
    return {
        "source_row_count": len(payload),
        "schema_fields": fields,
        "security_code_field": code_field,
        "security_code_count": len(codes),
        "security_codes": codes,
        "schema_validated": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="audit-output/market-scope/instrument-sources")
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    import requests

    summary: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sources": {},
        "database_accessed": False,
        "database_modified": False,
        "five_year_quotes_downloaded": False,
        "common_stock_classification_confirmed": False,
        "historical_universe_accepted": False,
        "quote_download_authorized": False,
    }

    for source_id, metadata in SOURCES.items():
        response = requests.get(
            metadata["url"], timeout=(8, 30),
            headers={"User-Agent": "tw-stock-ai-instrument-audit/1.0"},
        )
        response.raise_for_status()
        raw = response.content
        (output / f"{source_id}-raw.json").write_bytes(raw)
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
            inspected = inspect_payload(payload)
            status = "schema_validated"
            error = None
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            inspected = {
                "schema_validated": False,
                "schema_fields": [],
                "security_code_count": 0,
                "security_codes": [],
            }
            status = "schema_review_required"
            error = str(exc)

        summary["sources"][source_id] = {
            **metadata,
            "http_status": response.status_code,
            "content_type": response.headers.get("Content-Type", ""),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "fetch_status": status,
            "schema_error": error,
            **inspected,
            "exact_code_match_eligible": bool(inspected.get("schema_validated")),
        }

    (output / "official-instrument-source-audit.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "source_count": len(summary["sources"]),
        "schema_validated": sum(
            item["schema_validated"] for item in summary["sources"].values()
        ),
        "schema_review_required": sum(
            not item["schema_validated"] for item in summary["sources"].values()
        ),
        "database_modified": False,
        "five_year_quotes_downloaded": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
