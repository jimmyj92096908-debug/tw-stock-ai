"""AI 台股投資作戰系統統一行情下載入口。

此階段負責依市場呼叫 TWSE／TPEx 歷史日 K 模組。
預設不會自動掃描全市場，也不會下單；先用指定股票驗證整合流程。
"""

from __future__ import annotations

import argparse
import logging
from datetime import date

import market_data
import tpex_market_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def download_market(
    market: str,
    stock_id: str,
    start_year: int,
    end_year: int,
    start_month: int,
    end_month: int,
) -> int:
    """依市場呼叫對應的歷史行情模組。"""
    if market == "twse":
        return market_data.download_range(
            stock_id, start_year, end_year, start_month, end_month
        )
    if market == "tpex":
        return tpex_market_data.download_range(
            stock_id, start_year, end_year, start_month, end_month
        )
    raise ValueError(f"不支援的市場：{market}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI 台股投資作戰系統：上市／上櫃歷史日 K 統一下載入口"
    )
    parser.add_argument(
        "--market",
        choices=("twse", "tpex", "both"),
        default="both",
        help="twse=上市、tpex=上櫃、both=兩市場各下載指定股票",
    )
    parser.add_argument("--twse-stock-id", help="上市股票代號，例如 2330")
    parser.add_argument("--tpex-stock-id", help="上櫃股票代號，例如 6488")
    parser.add_argument("--start-year", type=int, default=date.today().year - 5)
    parser.add_argument("--end-year", type=int, default=date.today().year)
    parser.add_argument("--start-month", type=int, default=1)
    parser.add_argument("--end-month", type=int, default=12)
    args = parser.parse_args()

    if args.market in ("twse", "both") and not args.twse_stock_id:
        parser.error("--market twse/both 時必須提供 --twse-stock-id")
    if args.market in ("tpex", "both") and not args.tpex_stock_id:
        parser.error("--market tpex/both 時必須提供 --tpex-stock-id")

    jobs = []
    if args.market in ("twse", "both"):
        jobs.append(("twse", args.twse_stock_id))
    if args.market in ("tpex", "both"):
        jobs.append(("tpex", args.tpex_stock_id))

    total = 0
    for market, stock_id in jobs:
        logger.info("開始下載：市場=%s，股票=%s", market.upper(), stock_id)
        count = download_market(
            market,
            stock_id,
            args.start_year,
            args.end_year,
            args.start_month,
            args.end_month,
        )
        logger.info("%s %s 完成：%s 筆", market.upper(), stock_id, count)
        total += count

    logger.info("行情下載流程完成，總筆數：%s", total)
    logger.info("本程式僅下載資料，不會執行任何交易或下單。")


if __name__ == "__main__":
    main()
