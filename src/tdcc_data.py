"""Import official weekly TDCC shareholding distribution CSV.

The official open-data endpoint is a latest-snapshot file. We retain the
published as-of date from each row and never fabricate missing observations.
Only the four pilot stocks are persisted in this first implementation.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
from typing import Any

import psycopg
import requests

TDCC_URL = "https://openapi.tdcc.com.tw/v1/opendata/1-5"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TaiwanStockResearch/1.0)"}
STOCKS = {"6213": "twse", "4919": "twse", "7827": "twse", "8937": "tpex"}
RANGES = {
    "1": "1-999", "2": "1,000-5,000", "3": "5,001-10,000",
    "4": "10,001-15,000", "5": "15,001-20,000", "6": "20,001-30,000",
    "7": "30,001-40,000", "8": "40,001-50,000", "9": "50,001-100,000",
    "10": "100,001-200,000", "11": "200,001-400,000",
    "12": "400,001-600,000", "13": "600,001-800,000",
    "14": "800,001-1,000,000", "15": "1,000,001以上",
    "17": "合計",
}


def _key(value: Any) -> str:
    return re.sub(r"[\s％%()（）\ufeff]", "", str(value or "")).strip()


def _number(value: Any) -> float | None:
    text = str(value if value is not None else "").replace(",", "").replace("%", "").strip()
    if text in ("", "-", "--", "—"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _date(value: Any) -> str | None:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    if len(text) == 7 and text.isdigit():
        return f"{int(text[:3]) + 1911}-{text[3:5]}-{text[5:]}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    return None


def parse_csv(content: bytes | str, stock_map: dict[str, str] | None = None) -> list[dict]:
    stock_map = stock_map or STOCKS
    if isinstance(content, bytes):
        stripped = content.lstrip()
        if stripped.startswith((b"{", b"[")):
            payload = json.loads(content.decode("utf-8-sig"))
            rows = payload if isinstance(payload, list) else payload.get("data", payload.get("result", []))
            if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
                raise RuntimeError("TDCC OpenAPI JSON 回應格式非預期")
            fields = list(dict.fromkeys(k for row in rows for k in row))
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
            text = buffer.getvalue()
        else:
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = content.decode("cp950")
    else:
        text = content.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise RuntimeError("TDCC CSV 缺少標題列")
    columns = {_key(name): name for name in reader.fieldnames}
    aliases = {
        "date": ("資料日期", "日期", "dataDate", "data_date", "date", "asOfDate", "as_of_date"),
        "stock": ("證券代號", "股票代號", "代號", "stockCode", "stock_code", "securityCode", "security_code", "symbol"),
        "level": ("持股分級", "持股級距", "holdingLevel", "holding_level", "level", "range"),
        "holders": ("人數", "股東人數", "holders", "holderCount", "holder_count"),
        "shares": ("股數", "持有股數", "shares", "shareCount", "share_count"),
        "percent": ("占集保庫存數比例", "占集保庫存數比例%", "持股比例", "proportion", "percentage", "sharePercent", "share_percent"),
    }
    selected = {}
    for field, names in aliases.items():
        selected[field] = next((columns[_key(n)] for n in names if _key(n) in columns), None)
        if selected[field] is None:
            raise RuntimeError(f"TDCC 回應缺少必要欄位：{names}；實際欄位={reader.fieldnames}")

    output = []
    for row in reader:
        code = str(row.get(selected["stock"], "")).strip()
        if code not in stock_map:
            continue
        as_of = _date(row.get(selected["date"]))
        level_raw = str(row.get(selected["level"], "")).strip()
        level_match = re.search(r"\d+", level_raw)
        level = level_match.group(0) if level_match else level_raw
        if level == "16":
            continue
        holder_range = RANGES.get(level)
        if holder_range is None:
            raise RuntimeError(f"TDCC {code} 未知持股分級：{level_raw!r}")
        holders = _number(row.get(selected["holders"]))
        shares = _number(row.get(selected["shares"]))
        percent = _number(row.get(selected["percent"]))
        if not as_of or holders is None or shares is None or percent is None:
            raise RuntimeError(f"TDCC {code} {level_raw} 日期或數值欄位缺漏")
        if any(v < 0 for v in (holders, shares, percent)) or percent > 100.01:
            raise RuntimeError(f"TDCC {code} {holder_range} 數值超出合理範圍")
        output.append({
            "market": stock_map[code], "stock_id": code, "as_of_date": as_of,
            "holder_range": holder_range, "holder_count": int(holders),
            "share_count": int(shares), "share_percent": percent,
        })
    if not output:
        raise RuntimeError("TDCC CSV 未找到四檔測試股票資料")
    return output


def fetch_records() -> list[dict]:
    session = requests.Session()
    retry = requests.adapters.Retry(total=3, connect=3, read=2, backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset(["GET"]))
    session.mount("https://", requests.adapters.HTTPAdapter(max_retries=retry))
    try:
        response = session.get(TDCC_URL, headers={**HEADERS, "Accept": "application/json"}, timeout=(15, 60))
        response.raise_for_status()
    except requests.RequestException as primary_error:
        print(f"TDCC OpenAPI 連線失敗，改用舊版官方 CSV：{primary_error}")
        response = session.get("https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5", headers=HEADERS, timeout=(15, 60))
        response.raise_for_status()
    records = parse_csv(response.content)
    dates = {r["as_of_date"] for r in records}
    if len(dates) != 1:
        raise RuntimeError(f"TDCC 同批資料日期不一致：{sorted(dates)}")
    present = {r["stock_id"] for r in records}
    for code in STOCKS:
        if code not in present:
            raise RuntimeError(f"TDCC 當期資料缺少測試股票 {code}，不建立假資料")
    return records


def save_records(records: list[dict]) -> int:
    sql = """
        INSERT INTO tdcc_share_distribution (
            market, stock_id, as_of_date, holder_range, holder_count,
            share_count, share_percent, source, retrieved_at
        ) VALUES (
            %(market)s, %(stock_id)s, %(as_of_date)s, %(holder_range)s,
            %(holder_count)s, %(share_count)s, %(share_percent)s,
            'TDCC_OPEN_DATA_1_5', now()
        )
        ON CONFLICT (market, stock_id, as_of_date, holder_range) DO UPDATE SET
            holder_count=EXCLUDED.holder_count, share_count=EXCLUDED.share_count,
            share_percent=EXCLUDED.share_percent, source=EXCLUDED.source,
            retrieved_at=now()
    """
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, records)
    return len(records)


def main() -> None:
    argparse.ArgumentParser().parse_args()
    records = fetch_records()
    count = save_records(records)
    print(f"TDCC 成功寫入 {count} 筆級距資料；資料日期 {records[0]['as_of_date']}")
    for code in STOCKS:
        subset = [r for r in records if r["stock_id"] == code and r["holder_range"] != "合計"]
        big = sum(r["share_percent"] for r in subset if r["holder_range"] in (
            "400,001-600,000", "600,001-800,000", "800,001-1,000,000", "1,000,001以上"))
        print(code, "級距筆數", len(subset), "大額持股級距比例合計", round(big, 2), "%")


if __name__ == "__main__":
    main()
