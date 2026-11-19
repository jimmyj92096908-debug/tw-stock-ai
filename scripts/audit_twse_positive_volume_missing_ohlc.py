"""Audit TWSE records with positive volume but missing/invalid OHLC.

This is a read-only official-endpoint diagnostic. It never repairs prices or
writes to Neon. The JSON output is intended as a GitHub Actions artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

import requests

from scripts.download_five_year_market_history import request_payload
from src.market_data_bulk import parse_all_market_daily


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dates",
        default="2026-11-19,2026-11-18,2026-11-17,2025-11-19",
        help="Comma-separated YYYY-MM-DD dates",
    )
    parser.add_argument(
        "--output",
        default="audit-output/twse-positive-volume-missing-ohlc.json",
        help="Output JSON path",
    )
    args = parser.parse_args()
    dates = [date.fromisoformat(value.strip()) for value in args.dates.split(",") if value.strip()]
    if not dates or len(set(dates)) != len(dates):
        parser.error("provide one or more unique dates")

    session = requests.Session()
    records = []
    hashes = {}
    for trade_date in dates:
        raw, payload = request_payload(session, "twse", trade_date)
        rows = parse_all_market_daily(payload, "twse", trade_date.isoformat())
        hashes[trade_date.isoformat()] = hashlib.sha256(raw).hexdigest()
        for row in rows:
            volume = row.get("volume")
            if volume is None or volume <= 0 or row["ohlc_status"] == "complete":
                continue
            records.append({
                "trade_date": row["trade_date"],
                "stock_id": row["stock_id"],
                "name": row["name"],
                "volume": volume,
                "transactions": row.get("transactions"),
                "turnover": row.get("turnover"),
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "change": row.get("change"),
                "ohlc_status": row["ohlc_status"],
                "source": row["source"],
                "raw_sha256": hashes[trade_date.isoformat()],
            })

    if len(dates) > 1 and len(set(hashes.values())) != len(hashes):
        raise ValueError("TWSE endpoint returned identical raw payload hashes for different dates")

    counts = Counter(record["stock_id"] for record in records)
    report = {
        "report_type": "twse_positive_volume_missing_ohlc",
        "read_only": True,
        "database_accessed": False,
        "price_imputation_performed": False,
        "requested_dates": [value.isoformat() for value in dates],
        "raw_sha256_by_date": hashes,
        "record_count": len(records),
        "records_by_stock": dict(sorted(counts.items())),
        "records": records,
        "interpretation": (
            "These records have positive reported volume but incomplete or invalid OHLC. "
            "The audit does not infer prices, assign zero, or determine the underlying "
            "exchange trading mechanism. Keep them pending source-level review."
        ),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "record_count": len(records),
        "records_by_stock": dict(sorted(counts.items())),
        "database_accessed": False,
        "price_imputation_performed": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
