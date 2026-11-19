#!/usr/bin/env python3
"""Read-only audit of TPEx official current OTC stock-company snapshot.

The endpoint is an official current snapshot. Rows remain candidates until
instrument subtype and market eligibility are independently reconciled.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
TIMEOUT = (8, 25)
REQUIRED = ("SecuritiesCompanyCode", "CompanyName")


def normalize_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, list) or not payload:
        raise ValueError("TPEx response must be a non-empty JSON array")
    if not all(isinstance(row, dict) for row in payload):
        raise ValueError("TPEx response rows must be JSON objects")
    fields = sorted({key for row in payload for key in row})
    missing = [key for key in REQUIRED if key not in fields]
    if missing:
        raise ValueError(f"TPEx current OTC schema missing fields: {missing}")
    candidates, rejected, seen = [], [], set()
    for index, row in enumerate(payload, start=1):
        code = str(row.get("SecuritiesCompanyCode") or "").strip()
        name = str(row.get("CompanyName") or "").strip()
        abbreviation = str(row.get("CompanyAbbreviation") or "").strip()
        if not code or not name:
            rejected.append({"row": index, "reason": "missing_code_or_name"})
            continue
        if code in seen:
            rejected.append({"row": index, "stock_id": code, "reason": "duplicate_code"})
            continue
        seen.add(code)
        candidates.append({
            "stock_id": code, "name": name,
            "short_name": abbreviation, "market": "TPEX"
        })
    return {
        "source": "TPEx official current OTC stock basic-data OpenAPI",
        "url": URL, "schema_fields": fields,
        "source_row_count": len(payload), "candidate_count": len(candidates),
        "candidates": candidates, "rejected_rows": rejected,
        "snapshot_only": True, "historical_universe_accepted": False,
        "common_stock_classification_confirmed": False,
        "quote_download_authorized": False,
        "limitations": [
            "Current snapshot only; it does not reconstruct securities no longer listed.",
            "Instrument subtype and common-stock eligibility must be cross-checked before acceptance.",
            "This source is not used to infer five-year historical listing status."
        ]
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="audit-output/market-scope/tpex-current")
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    import requests

    response = None
    raw = b""
    payload = None
    attempts = 0
    last_json_error = None
    for attempt in range(1, 4):
        attempts = attempt
        response = requests.get(
            URL, timeout=TIMEOUT,
            headers={"User-Agent": "tw-stock-ai-universe-audit/1.0"}
        )
        response.raise_for_status()
        raw = response.content
        (output / f"tpex-current-otc-raw-attempt-{attempt}.json").write_bytes(raw)
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
            break
        except json.JSONDecodeError as exc:
            last_json_error = exc
            if attempt < 3:
                time.sleep(attempt * 2)

    if payload is None:
        preview = raw[max(0, last_json_error.pos - 100):last_json_error.pos + 100].decode(
            "utf-8", errors="replace"
        ) if last_json_error else ""
        raise RuntimeError(
            "TPEx returned invalid JSON after 3 attempts: "
            f"http_status={response.status_code if response else 'unknown'}, "
            f"bytes={len(raw)}, "
            f"content_length={response.headers.get('Content-Length', '') if response else ''}, "
            f"json_error={last_json_error}, context={preview!r}"
        )

    report = normalize_payload(payload)
    report.update({
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "http_status": response.status_code,
        "content_type": response.headers.get("Content-Type", ""),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "fetch_attempts": attempts,
        "database_accessed": False,
        "database_modified": False,
        "five_year_quotes_downloaded": False,
    })
    (output / "tpex-current-otc-raw.json").write_bytes(raw)
    (output / "tpex-current-otc-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (output / "tpex-current-otc-candidates.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["stock_id", "name", "short_name", "market"]
        )
        writer.writeheader()
        writer.writerows(report["candidates"])
    print(json.dumps({
        "source_rows": report["source_row_count"],
        "candidate_count": report["candidate_count"],
        "fetch_attempts": attempts,
        "common_stock_classification_confirmed": False,
        "database_modified": False,
        "five_year_quotes_downloaded": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
