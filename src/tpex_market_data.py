"""TPEx 上櫃股票歷史日 K 擷取模組。

使用櫃買中心官方個股日成交資訊查詢介面，按股票與月份下載。
輸出欄位與 src/market_data.py 的 TWSE 模組一致，分市場儲存，
不將最新行情快照誤當成歷史資料。
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "history" / "tpex"
TIMEOUT_SECONDS = 30
REQUEST_INTERVAL_SECONDS = 2
RETRY_POLICY = Retry(
    total=4,
    connect=4,
    read=4,
    status=4,
    backoff_factor=2,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET"}),
    raise_on_status=False,
)
SESSION = requests.Session()
SESSION.mount("https://", HTTPAdapter(max_retries=RETRY_POLICY))
FIELDNAMES = [
    "stock_id",
    "trade_date",
    "volume",
    "turnover",
    "open",
    "high",
    "low",
    "close",
    "change",
    "transactions",
    "source",
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def to_number(value: Any) -> float | int | None:
    """將櫃買中心數字字串轉成數值。"""
    if value is None:
        return None
    raw = str(value).strip().replace(",", "")
    if raw in {"", "--", "---", "X"}:
        return None
    try:
        number = float(raw)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def parse_roc_date(value: str) -> str:
    """將民國日期（例如 115/10/01）轉成 ISO 日期。"""
    match = re.fullmatch(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", value.strip())
    if not match:
        raise ValueError(f"無法辨識交易日期：{value!r}")
    year, month, day = map(int, match.groups())
    return date(year + 1911, month, day).isoformat()


def fetch_month(stock_id: str, year: int, month: int) -> list[dict[str, Any]]:
    """取得指定上櫃股票某月份的日成交資料。"""
    if not re.fullmatch(r"\d{4,6}", stock_id):
        raise ValueError("股票代號格式不正確，請輸入 4 至 6 位數字。")
    if not 1 <= month <= 12:
        raise ValueError("月份必須介於 1 至 12。")

    query_date = date(year, month, 1).strftime("%Y/%m/%d")
    response = SESSION.get(
        API_URL,
        params={"response": "json", "date": query_date, "code": stock_id},
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; tw-stock-ai/0.1)",
            "Accept": "application/json",
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("TPEx 回傳內容不是 JSON，可能遇到網站阻擋或暫時異常。") from exc

    if payload.get("stat") != "ok":
        logger.warning("%s %04d-%02d：TPEx 回覆 %s", stock_id, year, month, payload.get("stat"))
        return []

    tables = payload.get("tables") or []
    if not tables:
        logger.warning("%s %04d-%02d：TPEx 回傳沒有資料表", stock_id, year, month)
        return []

    raw_rows = tables[0].get("data") or []
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        if len(raw) < 9:
            logger.warning("略過欄位不足的資料列：%s", raw)
            continue
        rows.append(
            {
                "stock_id": stock_id,
                "trade_date": parse_roc_date(str(raw[0])),
                "volume": to_number(raw[1]),
                "turnover": to_number(raw[2]),
                "open": to_number(raw[3]),
                "high": to_number(raw[4]),
                "low": to_number(raw[5]),
                "close": to_number(raw[6]),
                "change": to_number(raw[7]),
                "transactions": to_number(raw[8]),
                "source": "TPEX_TRADING_STOCK",
            }
        )
    return rows


def save_rows(stock_id: str, rows: list[dict[str, Any]]) -> Path:
    """合併既有 CSV、依交易日去重並排序。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DATA_DIR / f"{stock_id}.csv"
    existing: dict[str, dict[str, Any]] = {}
    if output_path.exists():
        with output_path.open("r", newline="", encoding="utf-8-sig") as file:
            for row in csv.DictReader(file):
                existing[row["trade_date"]] = row
    for row in rows:
        existing[row["trade_date"]] = row

    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        for trade_date in sorted(existing):
            writer.writerow(existing[trade_date])

    logger.info("%s：本次取得 %s 筆，檔案累計 %s 筆", stock_id, len(rows), len(existing))
    return output_path


def download_range(
    stock_id: str,
    start_year: int,
    end_year: int,
    start_month: int = 1,
    end_month: int = 12,
) -> int:
    """按月份下載指定區間；可用月份參數限制測試範圍。"""
    if start_year > end_year or not 1 <= start_month <= 12 or not 1 <= end_month <= 12:
        raise ValueError("年份或月份區間不正確。")
    start = date(start_year, start_month, 1)
    end = date(end_year, end_month, 1)
    if start > end:
        raise ValueError("起始年月不可晚於結束年月。")

    today = date.today()
    total = 0
    current = start
    while current <= end and current <= date(today.year, today.month, 1):
        rows = fetch_month(stock_id, current.year, current.month)
        save_rows(stock_id, rows)
        total += len(rows)
        if current.year == end_year and current.month == end_month:
            break
        time.sleep(REQUEST_INTERVAL_SECONDS)
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="下載 TPEx 上櫃股票歷史日 K")
    parser.add_argument("--stock-id", required=True, help="上櫃股票代號，例如 6488")
    parser.add_argument("--start-year", type=int, default=date.today().year - 5)
    parser.add_argument("--end-year", type=int, default=date.today().year)
    parser.add_argument("--start-month", type=int, default=1)
    parser.add_argument("--end-month", type=int, default=12)
    args = parser.parse_args()
    count = download_range(
        args.stock_id, args.start_year, args.end_year, args.start_month, args.end_month
    )
    logger.info("完成：%s 共取得 %s 筆日 K 資料", args.stock_id, count)


if __name__ == "__main__":
    main()
