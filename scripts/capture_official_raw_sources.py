"""Capture official TWSE/TPEx responses for read-only OHLC evidence review.

Raw payloads are retained as workflow artifacts only; no database or price files are touched.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("RAW_SOURCE_OUTPUT", ROOT / "artifacts" / "official-raw-source"))
TIMEOUT = 45
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; tw-stock-ai-readonly-audit/1.0)",
    "Accept": "application/json,text/plain,*/*",
}
TARGETS = [
    {"market": "tpex", "stock_id": "1259", "trade_date": "2026-10-05"},
    {"market": "tpex", "stock_id": "1264", "trade_date": "2025-09-08"},
    {"market": "twse", "stock_id": "1101", "trade_date": "2026-11-18"},
]


def roc_date(value: Any) -> str | None:
    text = re.sub(r"[*＊]+$", "", str(value or "").strip())
    match = re.fullmatch(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", text)
    if not match:
        return None
    y, m, d = map(int, match.groups())
    try:
        return date(y + 1911, m, d).isoformat()
    except ValueError:
        return None


def capture(session: requests.Session, name: str, url: str, params: dict[str, str], target: dict) -> dict:
    response = session.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    raw = response.content
    suffix = "json" if "json" in response.headers.get("Content-Type", "").lower() else "txt"
    path = OUT / f'{target["market"]}-{target["stock_id"]}-{target["trade_date"]}-{name}.{suffix}'
    path.write_bytes(raw)
    try:
        payload = response.json()
        parse_error = None
    except ValueError:
        payload = None
        parse_error = "response_not_json"
    return {
        "endpoint": name,
        "requested_url": response.url,
        "http_status": response.status_code,
        "content_type": response.headers.get("Content-Type"),
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "raw_file": path.name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "byte_count": len(raw),
        "payload": payload,
        "parse_error": parse_error,
    }


def find_tpex_monthly_row(payload: dict | None, trade_date: str) -> list | None:
    if not isinstance(payload, dict):
        return None
    for table in payload.get("tables") or []:
        for row in table.get("data") or []:
            if row and roc_date(row[0]) == trade_date:
                return row
    return None


def find_twse_row(payload: dict | None, trade_date: str) -> list | None:
    if not isinstance(payload, dict):
        return None
    for row in payload.get("data") or []:
        if row and roc_date(row[0]) == trade_date:
            return row
    return None


def normalized_row(row: list | None) -> dict | None:
    if not row or len(row) < 9:
        return None
    keys = ("trade_date_raw", "volume", "turnover", "open", "high", "low", "close", "change", "transactions")
    return dict(zip(keys, row[:9]))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)
    report = {
        "read_only": True,
        "database_accessed": False,
        "database_modified": False,
        "raw_retention": "GitHub Actions artifact, 14 days",
        "targets": [],
    }
    for target in TARGETS:
        y, m, _ = map(int, target["trade_date"].split("-"))
        if target["market"] == "tpex":
            sources = [
                ("monthly_individual", "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock",
                 {"response": "json", "date": date(y, m, 1).strftime("%Y/%m/%d"), "code": target["stock_id"]}),
                ("bulk_daily", "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc",
                 {"response": "json", "date": target["trade_date"].replace("-", "/")}),
            ]
        else:
            sources = [
                ("twse_monthly_individual", "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY",
                 {"response": "json", "date": date(y, m, 1).strftime("%Y%m%d"), "stockNo": target["stock_id"]}),
            ]
        observations = []
        for name, url, params in sources:
            try:
                item = capture(session, name, url, params, target)
                if name == "monthly_individual":
                    row = find_tpex_monthly_row(item["payload"], target["trade_date"])
                elif name == "twse_monthly_individual":
                    row = find_twse_row(item["payload"], target["trade_date"])
                else:
                    # Keep bulk payload verbatim; do not guess its row schema.
                    row = None
                item["matching_raw_row"] = row
                item["normalized_row"] = normalized_row(row)
                item.pop("payload", None)
                observations.append(item)
            except requests.RequestException as exc:
                observations.append({"endpoint": name, "request_error": type(exc).__name__})
        report["targets"].append({**target, "observations": observations})
    (OUT / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if any("request_error" in obs for t in report["targets"] for obs in t["observations"]):
        raise SystemExit("One or more official source requests failed; inspect the partial artifact.")


if __name__ == "__main__":
    main()
