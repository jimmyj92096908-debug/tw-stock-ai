"""Read-only comparison of TPEx monthly historical quote endpoints.

No database access or writes. Compares JSON and CSV response formats from
the current TPEx tradingStock API, plus the legacy endpoint, for two known
missing-OHLC observations. CSV is a format comparison, not an independent source.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import requests

TARGETS = [
    {"stock_id": "1259", "trade_date": "2026-10-05"},
    {"stock_id": "1264", "trade_date": "2025-09-08"},
]
CURRENT_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
LEGACY_URL = "https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php"
OUT = Path("artifacts/tpex-monthly-endpoint-comparison")


def roc_month(year: int, month: int) -> str:
    return f"{year - 1911}/{month:02d}"


def normalize_roc_date(value: Any) -> str | None:
    text = re.sub(r"[*＊]+$", "", str(value or "").strip()).strip()
    match = re.fullmatch(r"(\d{2,3})[/.-](\d{1,2})[/.-](\d{1,2})", text)
    if not match:
        digits = re.fullmatch(r"(\d{3})(\d{2})(\d{2})", text)
        if not digits:
            return None
        y, m, d = map(int, digits.groups())
    else:
        y, m, d = map(int, match.groups())
    try:
        return date(y + 1911, m, d).isoformat()
    except ValueError:
        return None


def find_target_rows(payload: Any, target_date: str, layout: str) -> list[Any]:
    rows: list[Any] = []
    if layout == "current":
        for table in (payload.get("tables") or []) if isinstance(payload, dict) else []:
            rows.extend(table.get("data") or [])
    elif isinstance(payload, dict):
        rows.extend(payload.get("aaData") or [])
        rows.extend(payload.get("data") or [])
    found = []
    for row in rows:
        if isinstance(row, (list, tuple)) and row and normalize_roc_date(row[0]) == target_date:
            found.append(list(row))
        elif isinstance(row, dict):
            row_date = row.get("日期") or row.get("date") or row.get("交易日期")
            if normalize_roc_date(row_date) == target_date:
                found.append(row)
    return found


def request_endpoint(session: requests.Session, name: str, target: dict[str, str]) -> dict[str, Any]:
    year, month, _ = map(int, target["trade_date"].split("-"))
    if name in ("current_tradingStock", "current_tradingStock_csv"):
        url = CURRENT_URL
        response_format = "csv" if name.endswith("_csv") else "json"
        params = {"response": response_format, "date": date(year, month, 1).strftime("%Y/%m/%d"), "code": target["stock_id"]}
        layout = "current"
    else:
        url = LEGACY_URL
        params = {"l": "zh-tw", "d": roc_month(year, month), "stkno": target["stock_id"]}
        layout = "legacy"

    response = session.get(url, params=params, timeout=45)
    body = response.text
    suffix = "csv" if name.endswith("_csv") else "txt"
    raw_path = OUT / f'{target["stock_id"]}-{target["trade_date"]}-{name}.{suffix}'
    raw_path.write_text(body, encoding="utf-8-sig" if suffix == "csv" else "utf-8")
    result: dict[str, Any] = {
        "endpoint": name,
        "http_status": response.status_code,
        "content_type": response.headers.get("Content-Type"),
        "response_url": response.url,
        "raw_file": raw_path.name,
        "target": target,
        "rows": [],
        "json_parse_error": None,
    }
    if name.endswith("_csv"):
        try:
            dialect = csv.Sniffer().sniff(body[:4096], delimiters=",;\\t")
            parsed_rows = list(csv.reader(io.StringIO(body), dialect))
            result["csv_parse"] = "parsed"
            result["csv_row_count"] = len(parsed_rows)
            result["csv_header"] = parsed_rows[0] if parsed_rows else []
            result["csv_rows_preview"] = parsed_rows[:5]
            result["csv_target_date_matches"] = [row for row in parsed_rows if row and normalize_roc_date(row[0]) == target["trade_date"]] if parsed_rows else []
        except (csv.Error, UnicodeError) as exc:
            result["csv_parse"] = "failed"
            result["csv_parse_error"] = str(exc)
            result["body_preview"] = body[:1200]
        return result
    try:
        payload = response.json()
        result["top_level_keys"] = list(payload.keys()) if isinstance(payload, dict) else None
        result["status"] = payload.get("stat") if isinstance(payload, dict) else None
        result["rows"] = find_target_rows(payload, target["trade_date"], layout)
    except (ValueError, json.JSONDecodeError) as exc:
        result["json_parse_error"] = str(exc)
        result["body_preview"] = body[:1200]
    return result


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; tw-stock-ai-free-source-diagnostic/1.0)",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://www.tpex.org.tw/",
    })
    results = []
    for target in TARGETS:
        for endpoint in ("current_tradingStock", "current_tradingStock_csv", "legacy_st43_result"):
            try:
                result = request_endpoint(session, endpoint, target)
            except requests.RequestException as exc:
                result = {"endpoint": endpoint, "target": target, "request_error": str(exc), "rows": []}
            results.append(result)
            print(json.dumps(result, ensure_ascii=False))
    summary = {
        "read_only": True,
        "database_accessed": False,
        "database_modified": False,
        "source_policy": "free official TPEx endpoints only",
        "results": results,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
