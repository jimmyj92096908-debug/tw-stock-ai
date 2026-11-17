"""台股歷史日 K 擷取模組（第一階段：TWSE 上市股票）。

TWSE STOCK_DAY 每次查詢一檔股票的一個月份。
此模組先建立可重複執行、可去重的單檔月資料擷取流程。
尚未包含 TPEx 上櫃歷史行情；不會把最新日行情誤當成五年歷史資料。
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

API_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "history" / "twse"
TIMEOUT_SECONDS = 30
REQUEST_INTERVAL_SECONDS = 3
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def to_number(value: Any) -> float | int | None:
    """將交易所數字字串轉成數值；空白或無成交欄位回傳 None。"""
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
    """將民國日期（例如 115/01/05）轉為 ISO 日期。"""
    match = re.fullmatch(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", value.strip())
    if not match:
        raise ValueError(f"無法辨識交易日期：{value!r}")
    year, month, day = map(int, match.groups())
    return date(year + 1911, month, day).isoformat()


def fetch_month(stock_id: str, year: int, month: int) -> list[dict[str, Any]]:
    """取得指定上市股票某月份的日成交資料。"""
    if not re.fullmatch(r"\d{4,6}", stock_id):
        raise ValueError("股票代號格式不正確，請輸入 4 至 6 位數字。")
    if month < 1 or month > 12:
        raise ValueError("月份必須介於 1 至 12。")

    query_date = date(year, month, 1).strftime("%Y%m%d")
    response = requests.get(
        API_URL,
        params={"response": "json", "date": query_date, "stockNo": stock_id},
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
        raise RuntimeError("TWSE 回傳內容不是 JSON，可能遇到網站阻擋或暫時異常。") from exc

    if payload.get("stat") != "OK":
        # 非交易月份或無資料可能回傳非 OK 狀態；記錄狀態，避免偽造資料。
        logger.warning("%s %04d-%02d：TWSE 回覆 %s", stock_id, year, month, payload.get("stat"))
        return []

    rows: list[dict[str, Any]] = []
    for raw in payload.get("data", []):
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
                "source": "TWSE_STOCK_DAY",
            }
        )

    return rows


def save_rows(stock_id: str, rows: list[dict[str, Any]]) -> Path:
    """將資料合併寫入單檔 CSV，依交易日去重並排序。"""
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


def download_range(stock_id: str, start_year: int, end_year: int) -> int:
    """依月份逐筆下載指定年份區間，並在請求間隔暫停。"""
    if start_year > end_year:
        raise ValueError("起始年份不可晚於結束年份。")

    total = 0
    today = date.today()
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            if (year, month) > (today.year, today.month):
                continue
            rows = fetch_month(stock_id, year, month)
            save_rows(stock_id, rows)
            total += len(rows)
            time.sleep(REQUEST_INTERVAL_SECONDS)

    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="下載 TWSE 上市股票歷史日 K")
    parser.add_argument("--stock-id", required=True, help="上市股票代號，例如 2330")
    parser.add_argument("--start-year", type=int, default=date.today().year - 5)
    parser.add_argument("--end-year", type=int, default=date.today().year)
    args = parser.parse_args()

    count = download_range(args.stock_id, args.start_year, args.end_year)
    logger.info("完成：%s 共取得 %s 筆日 K 資料", args.stock_id, count)


if __name__ == "__main__":
    main()
