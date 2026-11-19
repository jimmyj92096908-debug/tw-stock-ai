"""Read-only reconciliation of TWSE bulk OHLC gaps against individual monthly quotes."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import requests

URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
DEFAULT_DATES = "2026-11-19,2026-11-18,2026-11-17,2025-11-19"
DEFAULT_STOCKS = "00682U,00707R,00775B,1538,2836A,2891C,3593,8112A"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; tw-stock-ai-source-audit/1.0)",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.twse.com.tw/",
}
TIMEOUT = (10, 30)


def parse_roc_date(value: Any) -> str | None:
    parts = str(value or "").strip().split("/")
    if len(parts) != 3:
        return None
    try:
        return date(int(parts[0]) + 1911, int(parts[1]), int(parts[2])).isoformat()
    except (TypeError, ValueError):
        return None


def parse_number(value: Any) -> int | float | None:
    raw = str(value or "").strip().replace(",", "")
    if raw in {"", "--", "---", "-", "X", "N/A"}:
        return None
    try:
        number = float(raw)
    except ValueError:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return int(number) if number.is_integer() else number


def parse_individual_month(payload: dict[str, Any], stock_id: str, requested_month: str) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("Individual quote response is not a JSON object")
    status = str(payload.get("stat") or "").strip()
    if status and status not in {"OK", "ok"}:
        raise ValueError(f"{stock_id}: official status {status!r}")
    fields = [str(item).strip() for item in payload.get("fields", [])]
    aliases = {
        "date": ("日期",),
        "volume": ("成交股數",),
        "turnover": ("成交金額",),
        "open": ("開盤價",),
        "high": ("最高價",),
        "low": ("最低價",),
        "close": ("收盤價",),
        "change": ("漲跌價差",),
        "transactions": ("成交筆數",),
    }
    idx = {key: next((i for i, field in enumerate(fields) if field in names), None)
           for key, names in aliases.items()}
    if any(idx[key] is None for key in ("date", "volume", "open", "high", "low", "close")):
        raise ValueError(f"{stock_id}: unexpected individual quote schema: {fields!r}")
    result = {}
    for raw in payload.get("data") or []:
        if len(raw) < len(fields):
            continue
        day = parse_roc_date(raw[idx["date"]])
        if not day or day[:7] != requested_month:
            continue
        item = {key: parse_number(raw[position]) if position is not None else None
                for key, position in idx.items() if key != "date"}
        item["trade_date"] = day
        item["source"] = "TWSE_STOCK_DAY"
        result[day] = item
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dates", default=DEFAULT_DATES)
    parser.add_argument("--stocks", default=DEFAULT_STOCKS)
    parser.add_argument("--output", default="audit-output/twse-individual-stock-reconciliation.json")
    parser.add_argument("--delay-seconds", type=float, default=0.5)
    args = parser.parse_args()
    if args.delay_seconds < 0.25:
        parser.error("delay must be at least 0.25 seconds")
    dates = sorted({date.fromisoformat(value.strip()) for value in args.dates.split(",") if value.strip()})
    stocks = sorted({value.strip() for value in args.stocks.split(",") if value.strip()})
    if not dates or not stocks:
        parser.error("dates and stocks must be non-empty")

    session = requests.Session()
    session.headers.update(HEADERS)
    monthly: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    hashes: dict[str, str] = {}
    errors: list[dict[str, str]] = []
    for stock_id in stocks:
        for month in sorted({day.strftime("%Y%m") for day in dates}):
            url_date = month + "01"
            try:
                response = session.get(
                    URL, params={"response": "json", "date": url_date, "stockNo": stock_id},
                    timeout=TIMEOUT,
                )
                response.raise_for_status()
                raw = response.content
                payload = response.json()
                hashes[f"{stock_id}:{month}"] = hashlib.sha256(raw).hexdigest()
                monthly[(stock_id, month)] = parse_individual_month(payload, stock_id, month[:4] + "-" + month[4:])
            except (requests.RequestException, ValueError) as exc:
                errors.append({"stock_id": stock_id, "month": month, "error": str(exc)[:300]})
            time.sleep(args.delay_seconds)

    comparisons = []
    for day in dates:
        for stock_id in stocks:
            item = monthly.get((stock_id, day.strftime("%Y%m")), {}).get(day.isoformat())
            if item is None:
                comparisons.append({
                    "trade_date": day.isoformat(), "stock_id": stock_id,
                    "individual_source_status": "no_matching_daily_row",
                })
                continue
            comparisons.append({
                "trade_date": day.isoformat(), "stock_id": stock_id,
                "individual_source_status": "matched",
                **item,
            })

    report = {
        "report_type": "twse_individual_stock_reconciliation",
        "read_only": True,
        "database_accessed": False,
        "database_modified": False,
        "requested_dates": [day.isoformat() for day in dates],
        "requested_stocks": stocks,
        "request_count": len(hashes) + len(errors),
        "raw_sha256_by_stock_month": hashes,
        "error_count": len(errors),
        "errors": errors,
        "matched_rows": sum(row.get("individual_source_status") == "matched" for row in comparisons),
        "no_matching_daily_row": sum(row.get("individual_source_status") == "no_matching_daily_row" for row in comparisons),
        "comparisons": comparisons,
        "interpretation": "Individual monthly quote rows are source evidence only. A match confirms an official individual row exists; it does not by itself explain why the bulk table omitted OHLC.",
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output), "request_count": report["request_count"],
        "matched_rows": report["matched_rows"],
        "no_matching_daily_row": report["no_matching_daily_row"],
        "error_count": len(errors), "database_accessed": False,
    }, ensure_ascii=False, sort_keys=True))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
