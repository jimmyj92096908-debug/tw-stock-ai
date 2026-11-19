"""Capture official TWSE/TPEx responses for read-only OHLC evidence review.

Raw payloads are retained as workflow artifacts only; no database or price files are touched.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.official_source_reconciliation import reconcile_tpex_payloads, reconcile_twse_payloads

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("RAW_SOURCE_OUTPUT", ROOT / "artifacts" / "official-raw-source"))
TIMEOUT = (8, 15)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; tw-stock-ai-readonly-audit/1.0)",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.tpex.org.tw/",
}
TARGETS = [
    {"market": "tpex", "stock_id": "1259", "trade_date": "2026-10-05"},
    {"market": "tpex", "stock_id": "1264", "trade_date": "2025-09-08"},
    {"market": "tpex", "stock_id": "1259", "trade_date": "2026-10-06"},
    {"market": "tpex", "stock_id": "1264", "trade_date": "2025-09-09"},
    {"market": "tpex", "stock_id": "1259", "trade_date": "2026-11-19"},
    {"market": "tpex", "stock_id": "1264", "trade_date": "2026-11-19"},
    {"market": "twse", "stock_id": "1101", "trade_date": "2026-11-18"},
    {"market": "twse", "stock_id": "1101", "trade_date": "2026-11-17"},
    {"market": "twse", "stock_id": "2330", "trade_date": "2026-11-18"},
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


def build_tpex_bulk_params(trade_date: str) -> dict[str, str]:
    """Build the TPEx whole-market daily quote request for all securities."""
    return {
        "response": "json",
        "date": trade_date.replace("-", "/"),
        "type": "AL",
    }


def find_tpex_monthly_row(payload: dict | None, trade_date: str) -> list | None:
    if not isinstance(payload, dict):
        return None
    for table in payload.get("tables") or []:
        for row in table.get("data") or []:
            if row and roc_date(row[0]) == trade_date:
                return row
    return None


def tpex_legacy_response_date(payload: dict | None) -> str | None:
    """Read the actual date carried by the TPEx legacy response, not the query string."""
    if not isinstance(payload, dict):
        return None
    dates: set[str] = set()
    raw_date = str(payload.get("date") or "").strip()
    if re.fullmatch(r"\\d{8}", raw_date):
        try:
            dates.add(date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8])).isoformat())
        except ValueError:
            return None
    for table in payload.get("tables") or []:
        parsed = roc_date(table.get("date"))
        if parsed:
            dates.add(parsed)
    return next(iter(dates)) if len(dates) == 1 else None


def find_tpex_legacy_daily_row(payload: dict | None, stock_id: str) -> list | None:
    """Find a stock row using the endpoint's declared fields; supports its current tables/data schema."""
    if not isinstance(payload, dict):
        return None
    for table in payload.get("tables") or []:
        fields = [str(value).strip() for value in (table.get("fields") or [])]
        code_index = next((i for i, field in enumerate(fields) if field in {"代號", "證券代號", "股票代號"}), None)
        if code_index is None:
            continue
        for row in table.get("data") or []:
            if len(row) > code_index and str(row[code_index]).strip() == stock_id:
                return row
    return None


def find_twse_row(payload: dict | None, trade_date: str) -> list | None:
    if not isinstance(payload, dict):
        return None
    for row in payload.get("data") or []:
        if row and roc_date(row[0]) == trade_date:
            return row
    return None


def find_twse_daily_market_row(payload: dict | None, stock_id: str) -> list | None:
    if not isinstance(payload, dict):
        return None
    for table in payload.get("tables") or []:
        fields = [str(x).strip() for x in (table.get("fields") or [])]
        code_index = next((i for i, field in enumerate(fields) if field in {"證券代號", "代號", "股票代號"}), None)
        if code_index is None:
            continue
        for row in table.get("data") or []:
            if len(row) > code_index and str(row[code_index]).strip() == stock_id:
                return row
    return None


def normalized_twse_daily_row(payload: dict | None, row: list | None) -> dict | None:
    if not isinstance(payload, dict) or not row:
        return None
    for table in payload.get("tables") or []:
        fields = [str(x).strip() for x in (table.get("fields") or [])]
        if len(row) != len(fields):
            continue
        raw = dict(zip(fields, row))
        aliases = {
            "stock_id": ("證券代號", "代號", "股票代號"),
            "name": ("證券名稱", "名稱", "股票名稱"),
            "volume_shares": ("成交股數",),
            "transaction_count": ("成交筆數",),
            "turnover": ("成交金額",),
            "open": ("開盤價",),
            "high": ("最高價",),
            "low": ("最低價",),
            "close": ("收盤價",),
        }
        result = {}
        for key, candidates in aliases.items():
            for candidate in candidates:
                if candidate in raw:
                    result[key] = raw[candidate]
                    break
        return result or None
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
    retry = Retry(
        total=1,
        connect=1,
        read=0,
        status=1,
        backoff_factor=0.25,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
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
                 build_tpex_bulk_params(target["trade_date"])),
                ("legacy_public_daily_close", "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php",
                 {"l": "zh-tw", "o": "json", "d": f"{y - 1911}/{m:02d}/{int(target['trade_date'].split('-')[2]):02d}"}),
            ]
        else:
            sources = [
                ("twse_monthly_individual", "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY",
                 {"response": "json", "date": date(y, m, 1).strftime("%Y%m%d"), "stockNo": target["stock_id"]}),
                ("twse_daily_market", "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
                 {"response": "json", "date": target["trade_date"].replace("-", ""), "type": "ALLBUT0999"}),
            ]
        observations = []
        source_payloads = {}
        for name, url, params in sources:
            try:
                item = capture(session, name, url, params, target)
                source_payloads[name] = item["payload"]
                time.sleep(0.15)
                if name == "monthly_individual":
                    row = find_tpex_monthly_row(item["payload"], target["trade_date"])
                elif name == "legacy_public_daily_close":
                    row = find_tpex_legacy_daily_row(item["payload"], target["stock_id"])
                    response_date = tpex_legacy_response_date(item["payload"])
                    item["response_trade_date"] = response_date
                    item["requested_trade_date_match"] = response_date == target["trade_date"]
                    item["candidate_raw_row"] = row
                    if response_date != target["trade_date"]:
                        row = None
                elif name == "twse_monthly_individual":
                    row = find_twse_row(item["payload"], target["trade_date"])
                elif name == "twse_daily_market":
                    row = find_twse_daily_market_row(item["payload"], target["stock_id"])
                else:
                    # Keep bulk payload verbatim; do not guess its row schema.
                    row = None
                item["matching_raw_row"] = row
                if name == "twse_daily_market":
                    item["normalized_row"] = normalized_twse_daily_row(item["payload"], row)
                elif name == "legacy_public_daily_close":
                    item["normalized_row"] = None  # Preserve row until the endpoint's field schema is verified.
                else:
                    item["normalized_row"] = normalized_row(row)
                item.pop("payload", None)
                observations.append(item)
            except requests.RequestException as exc:
                response = getattr(exc, "response", None)
                observations.append({
                    "endpoint": name,
                    "request_error": type(exc).__name__,
                    "http_status": response.status_code if response is not None else None,
                    "requested_url": getattr(response, "url", None),
                })
        target_report = {**target, "observations": observations}
        if target["market"] == "tpex":
            target_report["reconciliation"] = reconcile_tpex_payloads(
                source_payloads.get("monthly_individual"),
                source_payloads.get("bulk_daily"),
                target["stock_id"],
                target["trade_date"],
            )
        else:
            target_report["reconciliation"] = reconcile_twse_payloads(
                source_payloads.get("twse_monthly_individual"),
                source_payloads.get("twse_daily_market"),
                target["stock_id"],
                target["trade_date"],
            )
        report["targets"].append(target_report)
    (OUT / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if any("request_error" in obs for t in report["targets"] for obs in t["observations"]):
        raise SystemExit("One or more official source requests failed; inspect the partial artifact.")


if __name__ == "__main__":
    main()
