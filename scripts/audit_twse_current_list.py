#!/usr/bin/env python3
"""Read-only audit of the official TWSE current listed-company snapshot.

Records are review candidates only. This source is a current snapshot and is not
used to reconstruct historical listings or authorize quote downloads.
"""
from __future__ import annotations
import argparse, csv, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import requests

URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TIMEOUT = (8, 25)
REQUIRED = ("公司代號", "公司名稱", "上市日期")

def normalize_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, list) or not payload:
        raise ValueError("TWSE response must be a non-empty JSON array")
    if not all(isinstance(row, dict) for row in payload):
        raise ValueError("TWSE response rows must be JSON objects")
    fields = sorted({key for row in payload for key in row})
    missing = [key for key in REQUIRED if key not in fields]
    if missing:
        raise ValueError(f"TWSE current listed schema missing fields: {missing}")
    candidates = []
    rejected = []
    seen = set()
    for index, row in enumerate(payload, start=1):
        code = str(row.get("公司代號") or "").strip()
        name = str(row.get("公司名稱") or "").strip()
        date = str(row.get("上市日期") or "").strip()
        if not code or not name or not date:
            rejected.append({"row": index, "reason": "missing_code_name_or_listing_date"})
            continue
        if code in seen:
            rejected.append({"row": index, "stock_id": code, "reason": "duplicate_code"})
            continue
        seen.add(code)
        candidates.append({"stock_id": code, "name": name, "market": "TWSE", "listing_date_raw": date})
    return {
        "source": "TWSE official current listed-company OpenAPI",
        "url": URL,
        "schema_fields": fields,
        "source_row_count": len(payload),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "rejected_rows": rejected,
        "snapshot_only": True,
        "historical_universe_accepted": False,
        "common_stock_classification_confirmed": False,
        "quote_download_authorized": False,
        "limitations": [
            "Current snapshot only; it does not reconstruct securities no longer listed.",
            "Instrument subtype must be cross-checked before accepting common-stock-only scope.",
            "Listing date is retained as a raw source value pending date normalization and reconciliation."
        ]
    }

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", default="audit-output/market-scope/twse-current")
    a = p.parse_args()
    out = Path(a.output_dir); out.mkdir(parents=True, exist_ok=True)
    response = requests.get(URL, timeout=TIMEOUT, headers={"User-Agent":"tw-stock-ai-universe-audit/1.0"})
    response.raise_for_status()
    raw = response.content
    report = normalize_payload(response.json())
    report.update({
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "http_status": response.status_code,
        "content_type": response.headers.get("Content-Type", ""),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "database_accessed": False,
        "database_modified": False,
        "five_year_quotes_downloaded": False
    })
    (out / "twse-current-listed-raw.json").write_bytes(raw)
    (out / "twse-current-listed-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\\n", encoding="utf-8")
    with (out / "twse-current-listed-candidates.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["stock_id","name","market","listing_date_raw"])
        writer.writeheader(); writer.writerows(report["candidates"])
    print(json.dumps({"source_rows":report["source_row_count"],"candidate_count":report["candidate_count"],"common_stock_classification_confirmed":False,"database_modified":False,"five_year_quotes_downloaded":False},ensure_ascii=False,sort_keys=True))

if __name__ == "__main__":
    main()
