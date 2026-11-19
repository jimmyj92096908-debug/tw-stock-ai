"""唯讀 TPEx 原始資料診斷；不寫入資料庫或正式行情檔。"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tpex_market_data import API_URL, parse_raw_row  # noqa: E402

TARGETS = [
    {"stock_id": "1259", "year": 2026, "month": 10, "trade_date": "2026-10-05"},
    {"stock_id": "1264", "year": 2025, "month": 9, "trade_date": "2025-09-08"},
]


def roc_date(value: str) -> str | None:
    try:
        value = value.strip().rstrip("*＊")
        y, m, d = (int(x) for x in value.split("/"))
        return date(y + 1911, m, d).isoformat()
    except (ValueError, TypeError):
        return None


def main() -> None:
    out = ROOT / "artifacts" / "tpex-raw-diagnostic"
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; tw-stock-ai-diagnostic/1.0)",
        "Accept": "application/json",
    })
    results = []
    for target in TARGETS:
        params = {
            "response": "json",
            "date": date(target["year"], target["month"], 1).strftime("%Y/%m/%d"),
            "code": target["stock_id"],
        }
        response = session.get(API_URL, params=params, timeout=45)
        response.raise_for_status()
        payload = response.json()
        (out / f'{target["stock_id"]}-{target["year"]}-{target["month"]:02d}-raw.json').write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tables = payload.get("tables") or []
        raw_rows = (tables[0].get("data") or []) if tables else []
        matches = [row for row in raw_rows if row and roc_date(str(row[0])) == target["trade_date"]]
        parsed = []
        for row in matches:
            try:
                parsed.append(parse_raw_row(target["stock_id"], row))
            except Exception as exc:  # diagnostic must preserve raw evidence
                parsed.append({"parse_error": repr(exc)})
        results.append({
            **target,
            "http_status": response.status_code,
            "api_stat": payload.get("stat"),
            "table_fields": (tables[0].get("fields") or []) if tables else [],
            "matching_raw_rows": matches,
            "parsed_rows": parsed,
            "matching_rows_found": len(matches),
        })
        print(f'{target["stock_id"]} {target["trade_date"]}: '
              f'API={payload.get("stat")}, matched={len(matches)}')
    summary = {
        "read_only": True,
        "database_accessed": False,
        "database_modified": False,
        "targets": results,
    }
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if any(item["api_stat"] != "ok" or item["matching_rows_found"] == 0 for item in results):
        raise SystemExit("診斷未取得全部目標原始列；請檢查 artifact 中的 API 回應。")


if __name__ == "__main__":
    main()
