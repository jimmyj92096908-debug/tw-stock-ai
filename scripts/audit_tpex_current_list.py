#!/usr/bin/env python3
"""Read-only audit of TPEx official current OTC stock-company snapshot.

The endpoint is an official current snapshot. Rows remain candidates until
instrument subtype and market eligibility are independently reconciled.
"""
from __future__ import annotations
import argparse, csv, hashlib, json
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
        candidates.append({"stock_id": code, "name": name, "short_name": abbreviation, "market": "TPEX"})
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
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", default="audit-output/market-scope/tpex-current")
    a = p.parse_args()
    out = Path(a.output_dir); out.mkdir(parents=True, exist_ok=True)
    import requests
    response = requests.get(URL, timeout=TIMEOUT, headers={"User-Agent":"tw-stock-ai-universe-audit/1.0"})
    response.raise_for_status()
    raw = response.content
    report = normalize_payload(response.json())
    report.update({
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "http_status": response.status_code,
        "content_type": response.headers.get("Content-Type", ""),
        "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        "database_accessed": False, "database_modified": False,
        "five_year_quotes_downloaded": False
    })
    (out / "tpex-current-otc-raw.json").write_bytes(raw)
    (out / "tpex-current-otc-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    with (out / "tpex-current-otc-candidates.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["stock_id","name","short_name","market"])
        writer.writeheader(); writer.writerows(report["candidates"])
    print(json.dumps({"source_rows":report["source_row_count"],"candidate_count":report["candidate_count"],"common_stock_classification_confirmed":False,"database_modified":False,"five_year_quotes_downloaded":False},ensure_ascii=False,sort_keys=True))

if __name__ == "__main__":
    main()
