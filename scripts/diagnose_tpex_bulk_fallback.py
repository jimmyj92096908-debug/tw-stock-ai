"""Read-only probe of TPEx's official whole-market daily OHLC endpoint."""
from __future__ import annotations

import csv
import io
import json
from datetime import date
from pathlib import Path

import requests

API_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc"
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
        if result["eligible"]:
            if result["high"] < max(result["open"], result["close"], result["low"]) or result["low"] > min(result["open"], result["close"], result["high"]):
                result["eligible"] = False
                result["validation_error"] = "inconsistent_ohlc_range"
        return result
    return None


def decode_response(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp950", "big5"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("unknown", content, 0, min(1, len(content)), "unsupported CSV encoding")


def main() -> None:
    out = Path("artifacts/tpex-bulk-fallback")
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; tw-stock-ai-diagnostic/1.0)"})
    results = []
    for target in TARGETS:
        year, month, day = map(int, target["trade_date"].split("-"))
        params = {
            "date": date(year, month, day).strftime("%Y/%m/%d"),
            "type": "EW",
            "id": "",
            "response": "csv",
            "order": "0",
            "sort": "asc",
        }
        response = session.get(API_URL, params=params, timeout=60, headers={"Referer": "https://www.tpex.org.tw/"})
        response.raise_for_status()
        raw = decode_response(response.content)
        (out / f'{target["stock_id"]}-{target["trade_date"]}.csv').write_text(raw, encoding="utf-8-sig")
        parsed = parse_csv_payload(raw, target["stock_id"])
        results.append({
            **target,
            "http_status": response.status_code,
            "source": "TPEx official afterTrading/otc",
            "parsed": parsed,
            "fallback_available": bool(parsed and parsed.get("eligible")),
        })
        print(f'{target["stock_id"]} {target["trade_date"]}: fallback_available={bool(parsed and parsed.get("eligible"))}')
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
