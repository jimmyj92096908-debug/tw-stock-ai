"""Resumable five-year official bulk daily history downloader.

Downloads one date at a time from public TWSE/TPEx endpoints. It writes only
local JSON/JSONL evidence files; it has no database integration and never
repairs missing OHLC. TPEx public OTC quotes exclude fixed-price transactions.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests

from src.market_data_bulk import parse_all_market_daily

TWSE_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TPEX_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; tw-stock-ai-history-audit/1.0)",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.twse.com.tw/",
}
TIMEOUT = (10, 30)
MAX_ATTEMPTS = 4


def trading_weekdays(start: date, end: date):
    """Yield weekdays in the inclusive range; exchange holidays are recorded as non-data days."""
    current = start
    while current <= end:
        if current.weekday() < 5:
            yield current
        current += timedelta(days=1)


def request_payload(session: requests.Session, market: str, trade_date: date) -> tuple[bytes, dict[str, Any]]:
    day = trade_date.isoformat()
    if market == "twse":
        url = TWSE_URL
        params = {"response": "json", "date": trade_date.strftime("%Y%m%d"), "type": "ALLBUT0999"}
    elif market == "tpex":
        url = TPEX_URL
        params = {"response": "json", "date": trade_date.strftime("%Y/%m/%d"), "type": "AL"}
    else:
        raise ValueError("market must be twse or tpex")

    last_error = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = session.get(url, params=params, timeout=TIMEOUT)
            response.raise_for_status()
            raw = response.content
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Official response is not a JSON object")
            return raw, payload
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt + 1 < MAX_ATTEMPTS:
                time.sleep(min(2 ** attempt, 8) + random.uniform(0, 0.25))
    raise RuntimeError(f"{market} {day}: request failed after {MAX_ATTEMPTS} attempts: {last_error}")


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def load_completed(manifest: Path) -> set[tuple[str, str]]:
    completed: set[tuple[str, str]] = set()
    if not manifest.exists():
        return completed
    for line in manifest.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
            if item.get("status") == "success":
                completed.add((item["market"], item["trade_date"]))
        except (ValueError, KeyError, TypeError):
            continue
    return completed


def append_manifest(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")


def download_range(start: date, end: date, output: Path, markets: list[str], delay: float = 0.5) -> dict[str, int]:
    if start > end:
        raise ValueError("start date must be on or before end date")
    if delay < 0.25:
        raise ValueError("delay must be at least 0.25 seconds to limit load on public endpoints")

    output.mkdir(parents=True, exist_ok=True)
    manifest = output / "manifest.jsonl"
    completed = load_completed(manifest)
    counts = {"success": 0, "skipped": 0, "failed": 0}
    session = requests.Session()
    session.headers.update(HEADERS)

    for day in trading_weekdays(start, end):
        day_text = day.isoformat()
        for market in markets:
            key = (market, day_text)
            if key in completed:
                counts["skipped"] += 1
                continue
            try:
                raw, payload = request_payload(session, market, day)
                raw_path = output / "raw" / market / f"{day_text}.json.gz"
                raw_bytes = gzip.compress(raw)
                # Parse first. A rejected or mismatched response is not marked complete.
                rows = parse_all_market_daily(payload, market, day_text)
                rows_path = output / "rows" / market / f"{day_text}.jsonl"
                row_bytes = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows).encode("utf-8")
                atomic_write(raw_path, raw_bytes)
                atomic_write(rows_path, row_bytes)
                append_manifest(manifest, {
                    "market": market,
                    "trade_date": day_text,
                    "status": "success",
                    "row_count": len(rows),
                    "raw_path": str(raw_path.relative_to(output)),
                    "rows_path": str(rows_path.relative_to(output)),
                    "source_scope": "TWSE_MI_INDEX_ALLBUT0999" if market == "twse" else "TPEX_OTC_EXCLUDING_FIXED_PRICE",
                })
                completed.add(key)
                counts["success"] += 1
            except Exception as exc:  # record bounded failures; resume safely on next invocation
                append_manifest(manifest, {
                    "market": market,
                    "trade_date": day_text,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                })
                counts["failed"] += 1
            time.sleep(delay)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD, inclusive")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD, inclusive")
    parser.add_argument("--output-dir", default="artifacts/five-year-market-history")
    parser.add_argument("--markets", nargs="+", choices=("twse", "tpex"), default=("twse", "tpex"))
    parser.add_argument("--delay-seconds", type=float, default=0.5)
    args = parser.parse_args()
    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    counts = download_range(start, end, Path(args.output_dir), args.markets, args.delay_seconds)
    print(json.dumps({"read_only": True, "database_accessed": False, "database_modified": False, **counts}, ensure_ascii=False))
    if counts["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
