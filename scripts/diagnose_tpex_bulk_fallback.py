"""Probe TPEx's public daily-close endpoint using the exact page form contract.

Read-only: no database access or writes.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date
from pathlib import Path

import requests

API_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc"
PAGE_URL = "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/mi-pricing.html"
TARGETS = [
    {"stock_id": "1259", "trade_date": "2026-10-05"},
    {"stock_id": "1264", "trade_date": "2025-09-08"},
]


def number(value: str):
    value = (value or "").replace(",", "").strip()
    if value in {"", "--", "---", "----", "X"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def find_index(header: list[str], *candidates: str) -> int:
    normalized = [str(value).strip().replace(" ", "") for value in header]
    wanted = {candidate.replace(" ", "") for candidate in candidates}
    return next((i for i, value in enumerate(normalized) if value in wanted), -1)


def parse_csv_payload(text: str, stock_id: str) -> dict | None:
    """Keep legacy CSV parser tests; never treats missing OHLC as valid."""
    rows = list(csv.reader(io.StringIO(text)))
    header_index = next(
        (i for i, row in enumerate(rows)
         if find_index(row, "代號", "證券代號") >= 0
         and find_index(row, "開盤價", "開盤") >= 0
         and find_index(row, "最高價", "最高") >= 0
         and find_index(row, "最低價", "最低") >= 0
         and find_index(row, "收盤價", "收盤") >= 0),
        -1,
    )
    if header_index < 0:
        raise ValueError("CSV 找不到包含代號及完整 OHLC 欄位的表頭")
    header = rows[header_index]
    indexes = {
        "stock_id": find_index(header, "代號", "證券代號"),
        "open": find_index(header, "開盤價", "開盤"),
        "high": find_index(header, "最高價", "最高"),
        "low": find_index(header, "最低價", "最低"),
        "close": find_index(header, "收盤價", "收盤"),
    }
    for row in rows[header_index + 1:]:
        if indexes["stock_id"] >= len(row) or row[indexes["stock_id"]].strip().strip('="') != stock_id:
            continue
        result = {key: number(row[index]) for key, index in indexes.items() if key != "stock_id"}
        result["stock_id"] = stock_id
        result["eligible"] = all(result[key] is not None and result[key] > 0 for key in ("open", "high", "low", "close"))
        if result["eligible"] and (result["high"] < max(result["open"], result["close"], result["low"]) or result["low"] > min(result["open"], result["close"], result["high"])):
            result["eligible"] = False
            result["validation_error"] = "inconsistent_ohlc_range"
        return result
    return None


def main() -> None:
    out = Path("artifacts/tpex-bulk-fallback")
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
        "Referer": PAGE_URL,
        "Origin": "https://www.tpex.org.tw",
        "X-Requested-With": "XMLHttpRequest",
    })
    results = []
    for target in TARGETS:
        parsed_date = date.fromisoformat(target["trade_date"])
        form = {"date": parsed_date.strftime("%Y/%m/%d"), "type": "EW", "response": "json"}
        response = session.post(API_URL, data=form, timeout=60)
        record = {
            **target,
            "http_status": response.status_code,
            "request_method": "POST",
            "request_form": form,
            "source": "TPEx official mi-pricing page form contract",
        }
        response.raise_for_status()
        try:
            payload = response.json()
            raw_path = out / f'{target["stock_id"]}-{target["trade_date"]}.json'
            raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            record["response_format"] = "json"
            record["top_level_keys"] = list(payload) if isinstance(payload, dict) else None
            record["api_stat"] = payload.get("stat") if isinstance(payload, dict) else None
            tables = payload.get("tables", []) if isinstance(payload, dict) else []
            record["table_count"] = len(tables) if isinstance(tables, list) else None
            record["table_summaries"] = []
            target_matches = []
            for table_index, table in enumerate(tables if isinstance(tables, list) else []):
                data = table.get("data") if isinstance(table, dict) else None
                record["table_summaries"].append({
                    "index": table_index,
                    "keys": list(table) if isinstance(table, dict) else [],
                    "title": table.get("title") if isinstance(table, dict) else None,
                    "subtitle": table.get("subtitle") if isinstance(table, dict) else None,
                    "data_type": type(data).__name__,
                    "data_rows": len(data) if isinstance(data, list) else None,
                    "data_preview": data[:3] if isinstance(data, list) else data,
                })
                if isinstance(data, list):
                    for row in data:
                        if target["stock_id"] in json.dumps(row, ensure_ascii=False):
                            target_matches.append(row)
            record["target_rows"] = target_matches[:5]
            record["fallback_available"] = bool(target_matches)
        except (ValueError, json.JSONDecodeError) as exc:
            raw_path = out / f'{target["stock_id"]}-{target["trade_date"]}.txt'
            raw_path.write_text(response.text, encoding="utf-8")
            record.update({
                "response_format": "non_json",
                "parse_error": str(exc),
                "response_preview": response.text[:3000],
                "fallback_available": False,
            })
        results.append(record)
        print(json.dumps(record, ensure_ascii=False))
    summary = {
        "read_only": True,
        "database_accessed": False,
        "database_modified": False,
        "results": results,
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
