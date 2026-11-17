"""上市／上櫃歷史日 K 批次下載器。

預設每個市場最多下載 2 檔，避免誤觸發全市場長時間大量請求。
使用 --offset 與 --limit 分批續跑；只有明確指定較大 limit 才會擴大批次。
資料保存在 Actions runner 的暫存工作目錄，必須由 workflow artifact 或後續
雲端資料庫持久化；本程式不會把歷史行情 commit 回 Git。
"""

from __future__ import annotations

import argparse
import csv
import logging
from datetime import date
from pathlib import Path

import market_data
import stock_list
import tpex_market_data

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_PATH = ROOT / "data" / "history" / "batch_summary.csv"
MARKET_MAP = {"twse": "上市", "tpex": "上櫃"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def select_stocks(market: str, offset: int, limit: int, stock_ids: list[str] | None = None) -> list[dict[str, str]]:
    """從官方股票清單選取指定市場的分批股票，或使用明確指定的代碼。"""
    if offset < 0 or limit < 1:
        raise ValueError("offset 必須大於等於 0，limit 必須大於 0。")

    if stock_ids:
        unique_ids = list(dict.fromkeys(stock_ids))
        for stock_id in unique_ids:
            if not stock_id.isdigit() or len(stock_id) != 4:
                raise ValueError(f"股票代碼格式不正確：{stock_id}")
        return [{"stock_id": code, "stock_name": "", "market": MARKET_MAP[market], "industry": ""} for code in unique_ids]

    rows = stock_list.build_stock_list()
    selected = [row for row in rows if row["market"] == MARKET_MAP[market]]
    selected.sort(key=lambda row: row["stock_id"])
    return selected[offset : offset + limit]


def download_one(market: str, stock_id: str, start_year: int, end_year: int, start_month: int, end_month: int) -> int:
    """下載單檔股票指定年月範圍。"""
    module = market_data if market == "twse" else tpex_market_data
    return module.download_range(
        stock_id,
        start_year,
        end_year,
        start_month,
        end_month,
    )


def save_summary(rows: list[dict[str, str]]) -> None:
    """輸出本次批次執行摘要。"""
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    fields = ["market", "stock_id", "stock_name", "rows_downloaded", "status"]
    with SUMMARY_PATH.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    today = date.today()
    parser = argparse.ArgumentParser(description="台股上市／上櫃歷史日 K 分批下載")
    parser.add_argument("--market", choices=("twse", "tpex", "both"), default="both")
    parser.add_argument("--offset", type=int, default=0, help="每個市場的股票清單起始位移")
    parser.add_argument("--limit", type=int, default=2, help="每個市場最多下載幾檔；預設 2 檔")
    parser.add_argument("--twse-stock-ids", default="", help="指定上市代碼，逗號分隔；不填則讀取官方清單")
    parser.add_argument("--tpex-stock-ids", default="", help="指定上櫃代碼，逗號分隔；不填則讀取官方清單")
    parser.add_argument("--start-year", type=int, default=today.year - 5)
    parser.add_argument("--end-year", type=int, default=today.year)
    parser.add_argument("--start-month", type=int, default=1)
    parser.add_argument("--end-month", type=int, default=12)
    args = parser.parse_args()

    if args.start_year > args.end_year or not 1 <= args.start_month <= 12 or not 1 <= args.end_month <= 12:
        parser.error("年份或月份範圍不正確。")

    jobs = []
    if args.market in ("twse", "both"):
        ids = [value.strip() for value in args.twse_stock_ids.split(",") if value.strip()]
        jobs.append(("twse", ids or None))
    if args.market in ("tpex", "both"):
        ids = [value.strip() for value in args.tpex_stock_ids.split(",") if value.strip()]
        jobs.append(("tpex", ids or None))

    summary: list[dict[str, str]] = []
    failed = 0
    for market, ids in jobs:
        logger.info("取得 %s 股票清單（offset=%s, limit=%s）", MARKET_MAP[market], args.offset, args.limit)
        selected = select_stocks(market, args.offset, args.limit, ids)
        logger.info("%s 本批選取 %s 檔股票", MARKET_MAP[market], len(selected))
        for stock in selected:
            stock_id = stock["stock_id"]
            try:
                count = download_one(
                    market, stock_id, args.start_year, args.end_year,
                    args.start_month, args.end_month,
                )
                summary.append({
                    "market": MARKET_MAP[market],
                    "stock_id": stock_id,
                    "stock_name": stock["stock_name"],
                    "rows_downloaded": str(count),
                    "status": "success",
                })
                logger.info("%s %s 完成：%s 筆", market.upper(), stock_id, count)
            except Exception:
                failed += 1
                logger.exception("%s %s 下載失敗", market.upper(), stock_id)
                summary.append({
                    "market": MARKET_MAP[market],
                    "stock_id": stock_id,
                    "stock_name": stock["stock_name"],
                    "rows_downloaded": "0",
                    "status": "failed",
                })

    save_summary(summary)
    succeeded = sum(row["status"] == "success" for row in summary)
    logger.info("批次完成：成功 %s 檔，失敗 %s 檔", succeeded, failed)
    logger.info("摘要檔案：%s", SUMMARY_PATH)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
