"""Refresh the four tracked stocks, import OHLC data, and recalculate indicators."""
from __future__ import annotations

import logging
import os
from datetime import date

import psycopg
from psycopg.rows import dict_row

import market_data
import tpex_market_data
from db_storage import import_history
from calculate_technicals import calculate_stock as calculate_technical_stock
from calculate_smc import calculate_stock as calculate_smc_stock

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TARGETS = (
    ("twse", "6213", "聯茂"),
    ("tpex", "8937", "合騏"),
    ("twse", "4919", "新唐"),
    ("twse", "7827", "漢康"),
)


def previous_month(today: date) -> date:
    if today.month == 1:
        return date(today.year - 1, 12, 1)
    return date(today.year, today.month - 1, 1)


def next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def get_download_start(conn: psycopg.Connection, market: str, stock_id: str, today: date) -> date:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(trade_date) AS latest_date FROM daily_prices WHERE market=%s AND stock_id=%s",
            (market, stock_id),
        )
        latest = cur.fetchone()["latest_date"]
    fallback = date(today.year - 5, 1, 1)
    if latest is None:
        return fallback
    latest_month = date(latest.year, latest.month, 1)
    retry_month = previous_month(today)
    # Re-fetch the latest stored month to capture late revisions. If the data
    # is older, continue from the month after the last stored month.
    if latest_month < retry_month:
        return next_month(latest_month)
    return retry_month


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL secret is required; never hard-code credentials.")

    today = date.today()
    with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=20) as conn:
        for market, stock_id, name in TARGETS:
            start = get_download_start(conn, market, stock_id, today)
            logger.info(
                "更新 %s %s：%04d-%02d 至 %04d-%02d",
                name, stock_id, start.year, start.month, today.year, today.month,
            )
            module = market_data if market == "twse" else tpex_market_data
            count = module.download_range(
                stock_id, start.year, today.year, start.month, today.month
            )
            if count == 0:
                logger.warning("%s %s 本次未取得新資料；後續仍會保留既有資料", name, stock_id)
            else:
                logger.info("%s %s 本次下載 %s 筆", name, stock_id, count)

    imported = import_history(__import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "history")
    logger.info("Neon 行情匯入完成：%s 筆", imported)

    with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=20) as conn:
        for market, stock_id, name in TARGETS:
            tech_count = calculate_technical_stock(conn, market, stock_id)
            smc_count = calculate_smc_stock(conn, market, stock_id)
            logger.info("%s %s：技術指標 %s 筆；SMC %s 筆", name, stock_id, tech_count, smc_count)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT market, stock_id, MAX(trade_date) AS latest_date, COUNT(*) AS rows
                FROM daily_prices
                WHERE (market, stock_id) IN (('twse','6213'),('tpex','8937'),('twse','4919'),('twse','7827'))
                GROUP BY market, stock_id
                ORDER BY market, stock_id
                """
            )
            for row in cur.fetchall():
                logger.info(
                    "VERIFY market=%s stock=%s latest=%s rows=%s",
                    row["market"], row["stock_id"], row["latest_date"], row["rows"],
                )


if __name__ == "__main__":
    main()
