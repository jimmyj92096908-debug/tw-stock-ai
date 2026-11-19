"""Probe TPEx's public daily-close endpoint using the exact page form contract.

Read-only: no database access or writes.
"""
from __future__ import annotations

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
        # Official page date input stores YYYYMMDD; tables.js POSTs serialized
        # form fields and requests JSON by default.
        form = {"date": parsed_date.strftime("%Y%m%d"), "type": "EW", "response": "json"}
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
