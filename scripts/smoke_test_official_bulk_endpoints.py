"""Bounded live smoke test for official TWSE and TPEx bulk quote endpoints.

Fetches exactly one requested date from each exchange, parses in memory, and
prints compact diagnostics. It does not write files or access any database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from datetime import date

import requests

from scripts.download_five_year_market_history import request_payload
from src.market_data_bulk import parse_all_market_daily


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dates", default="2026-11-19,2026-11-18,2026-11-17,2025-11-19",
        help="Comma-separated YYYY-MM-DD dates; each response date is strictly validated",
    )
    args = parser.parse_args()
    trade_dates = [date.fromisoformat(value.strip()) for value in args.dates.split(",") if value.strip()]
    if not trade_dates or len(set(trade_dates)) != len(trade_dates):
        parser.error("provide one or more unique dates")

    session = requests.Session()
    results = []
    for trade_date in trade_dates:
        for market in ("twse", "tpex"):
            raw, payload = request_payload(session, market, trade_date)
            rows = parse_all_market_daily(payload, market, trade_date.isoformat())
            statuses = Counter(row["ohlc_status"] for row in rows)
            missing_rows = [row for row in rows if row["ohlc_status"] != "complete"]
            missing_volume = Counter(
            "positive" if row["volume"] is not None and row["volume"] > 0 else
            "zero" if row["volume"] == 0 else "unknown"
            for row in missing_rows
            )
            positive_volume_missing = [
            row for row in missing_rows
            if row["volume"] is not None and row["volume"] > 0
            ]
            results.append({
            "market": market,
            "requested_date": trade_date.isoformat(),
            "rows": len(rows),
            "ohlc_status_counts": dict(sorted(statuses.items())),
            "raw_bytes": len(raw),
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "source_scope": (
                "TWSE listed-market daily quotes"
                if market == "twse"
                else "TPEx OTC daily quotes excluding fixed-price transactions"
            ),
            "sample_stock_ids": [row["stock_id"] for row in rows[:5]],
            "missing_ohlc_volume_class": dict(sorted(missing_volume.items())),
            "positive_volume_missing_ohlc": [
                {"stock_id": row["stock_id"], "name": row["name"], "volume": row["volume"], "transactions": row["transactions"]}
                for row in positive_volume_missing
            ],
            })
            time.sleep(0.5)

    hashes_differ = {
        market: len({item["raw_sha256"] for item in results if item["market"] == market}) > 1
        for market in ("twse", "tpex")
    }
    if len(trade_dates) > 1 and not all(hashes_differ.values()):
        raise ValueError(f"Identical raw response hashes across dates; possible stale endpoint: {hashes_differ}")

    print(json.dumps({
        "read_only": True,
        "database_accessed": False,
        "filesystem_written": False,
        "requested_dates": [value.isoformat() for value in trade_dates],
        "date_count": len(trade_dates),
        "endpoint_response_hashes_differ_by_date": hashes_differ,
        "results": results,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
