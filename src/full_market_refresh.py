"""Incrementally refresh rotating batches of all TWSE/TPEx listed stocks."""
from __future__ import annotations

import logging
import os
import time
from datetime import date

import psycopg
from psycopg.rows import dict_row

import market_data
import stock_list
import tpex_market_data
from build_adjusted_prices import build as build_adjusted_stock
from calculate_smc import calculate_stock as calculate_smc_stock
from calculate_technicals import calculate_stock as calculate_technical_stock

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
MARKET_MAP = {"上市": "twse", "上櫃": "tpex"}
REQUEST_INTERVAL = {"twse": 3, "tpex": 2}
DEFAULT_BATCH_SIZE = 5

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CREATE_STATE_SQL = """
CREATE TABLE IF NOT EXISTS market_data_refresh_state (
    market TEXT NOT NULL,
    stock_id VARCHAR(6) NOT NULL,
    last_attempt_at TIMESTAMPTZ,
    last_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (last_status IN ('pending', 'success', 'failed')),
    latest_trade_date DATE,
    rows_downloaded INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (market, stock_id),
    FOREIGN KEY (market, stock_id)
        REFERENCES stock_master (market, stock_id)
        ON UPDATE CASCADE ON DELETE CASCADE
)
"""


def month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def previous_month(value: date) -> date:
    if value.month == 1:
        return date(value.year - 1, 12, 1)
    return date(value.year, value.month - 1, 1)


def choose_start_month(latest_trade_date: date | None, today: date) -> date:
    """Newly listed stocks get up to five years; existing stocks refresh recent months."""
    floor = previous_month(today)
    if latest_trade_date is None:
        return date(today.year - 5, today.month, 1)
    return max(month_start(latest_trade_date), floor)


def upsert_universe(conn: psycopg.Connection, rows: list[dict[str, str]]) -> None:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(CREATE_STATE_SQL)
            cur.executemany(
                """
                INSERT INTO stock_master (market, stock_id, stock_name, industry)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (market, stock_id) DO UPDATE SET
                    stock_name=EXCLUDED.stock_name,
                    industry=EXCLUDED.industry,
                    updated_at=NOW()
                """,
                [
                    (MARKET_MAP[row["market"]], row["stock_id"], row["stock_name"], row["industry"])
                    for row in rows
                ],
            )
            cur.execute(
                """
                INSERT INTO market_data_refresh_state (market, stock_id)
                SELECT market, stock_id FROM stock_master
                ON CONFLICT (market, stock_id) DO NOTHING
                """
            )


def select_batch(conn: psycopg.Connection, market: str, limit: int) -> list[dict]:
    """Interleave previously unpriced stocks and existing priced stocks.

    A fixed 'all never-priced first' ordering can starve existing tickers for
    months when the candidate universe is large. Interleaving by rank keeps
    both initial coverage and existing market data moving forward at the
    configured request budget. No data is written in this selection step.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH candidates AS (
                SELECT sm.market, sm.stock_id, sm.stock_name,
                       MAX(dp.trade_date) FILTER (
                           WHERE dp.close IS NOT NULL
                       ) AS latest_trade_date,
                       st.last_attempt_at
                FROM stock_master sm
                LEFT JOIN daily_prices dp
                  ON dp.market=sm.market AND dp.stock_id=sm.stock_id
                LEFT JOIN market_data_refresh_state st
                  ON st.market=sm.market AND st.stock_id=sm.stock_id
                WHERE sm.market=%s
                GROUP BY sm.market, sm.stock_id, sm.stock_name, st.last_attempt_at
            ), numbered AS (
                SELECT market,stock_id,stock_name,latest_trade_date,
                       ROW_NUMBER() OVER (
                           PARTITION BY (latest_trade_date IS NULL)
                           ORDER BY last_attempt_at ASC NULLS FIRST,
                                    latest_trade_date ASC NULLS FIRST, stock_id
                       ) AS rotation_slot
                FROM candidates
            )
            SELECT market,stock_id,stock_name,latest_trade_date
            FROM numbered
            ORDER BY rotation_slot,
                     CASE WHEN latest_trade_date IS NULL THEN 0 ELSE 1 END,
                     stock_id
            LIMIT %s
            """,
            (market, limit),
        )
        return cur.fetchall()


def record_attempt(
    conn: psycopg.Connection,
    market: str,
    stock_id: str,
    status: str,
    rows_downloaded: int,
    latest_trade_date: date | None,
    error_message: str | None = None,
) -> None:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO market_data_refresh_state (
                    market, stock_id, last_attempt_at, last_status,
                    latest_trade_date, rows_downloaded, error_message, updated_at
                ) VALUES (%s, %s, NOW(), %s, %s, %s, %s, NOW())
                ON CONFLICT (market, stock_id) DO UPDATE SET
                    last_attempt_at=NOW(),
                    last_status=EXCLUDED.last_status,
                    latest_trade_date=EXCLUDED.latest_trade_date,
                    rows_downloaded=EXCLUDED.rows_downloaded,
                    error_message=EXCLUDED.error_message,
                    updated_at=NOW()
                """,
                (market, stock_id, status, latest_trade_date, rows_downloaded, error_message),
            )


def refresh_one(conn: psycopg.Connection, stock: dict, today: date) -> None:
    market, stock_id = stock["market"], stock["stock_id"]
    start = choose_start_month(stock["latest_trade_date"], today)
    module = market_data if market == "twse" else tpex_market_data
    logger.info(
        "更新 %s %s：%04d-%02d 至 %04d-%02d",
        market.upper(), stock_id, start.year, start.month, today.year, today.month,
    )
    try:
        count = module.download_range(
            stock_id, start.year, today.year, start.month, today.month
        )
        history_dir = ROOT / "data" / "history" / market
        csv_path = history_dir / f"{stock_id}.csv"
        if not csv_path.exists():
            raise RuntimeError("下載器未產生預期 CSV 檔案")
        from db_storage import upsert_csv
        # upsert_csv manages its own transaction. Do not use "with conn" here:
        # psycopg closes the connection when that context exits.
        upsert_csv(conn, csv_path, market)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(trade_date) AS latest FROM daily_prices WHERE market=%s AND stock_id=%s",
                (market, stock_id),
            )
            latest = cur.fetchone()["latest"]
        record_attempt(conn, market, stock_id, "success", count, latest)
        logger.info("%s %s 更新成功：本次取得 %s 筆；最新交易日 %s", market, stock_id, count, latest)
    except Exception as exc:
        logger.exception("%s %s 更新失敗", market, stock_id)
        record_attempt(conn, market, stock_id, "failed", 0, stock["latest_trade_date"], str(exc)[:2000])
        raise


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL secret is required; never hard-code credentials.")
    batch_size = int(os.environ.get("BATCH_SIZE", str(DEFAULT_BATCH_SIZE)))
    if not 1 <= batch_size <= 250:
        raise ValueError("BATCH_SIZE must be between 1 and 250.")

    universe = stock_list.build_stock_list()
    today = date.today()
    logger.info("官方股票清單共 %s 檔；每市場本次處理最多 %s 檔", len(universe), batch_size)

    failures: list[str] = []
    refreshed_this_run: list[dict[str, str]] = []
    with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=20) as conn:
        upsert_universe(conn, universe)
        for market in ("twse", "tpex"):
            batch = select_batch(conn, market, batch_size)
            logger.info("%s 本次輪替選取 %s 檔", market.upper(), len(batch))
            for index, stock in enumerate(batch):
                try:
                    refresh_one(conn, stock, today)
                    refreshed_this_run.append({"market": market, "stock_id": stock["stock_id"]})
                except Exception as exc:
                    failures.append(f"{market} {stock['stock_id']}: {exc}")
                if index < len(batch) - 1:
                    time.sleep(REQUEST_INTERVAL[market])

        # Build adjusted bars first; both technical and SMC calculations read them.
        for stock in refreshed_this_run:
            try:
                adjusted_count = build_adjusted_stock(conn, stock["market"], stock["stock_id"])
                if adjusted_count <= 0:
                    raise RuntimeError("還原行情建立筆數為 0")
                logger.info(
                    "%s %s 還原行情建立完成：%s 筆",
                    stock["market"].upper(), stock["stock_id"], adjusted_count,
                )
                technical_count = calculate_technical_stock(conn, stock["market"], stock["stock_id"])
                smc_count = calculate_smc_stock(conn, stock["market"], stock["stock_id"])
                if technical_count <= 0 or smc_count <= 0:
                    raise RuntimeError(
                        f"指標資料不足：technicals={technical_count}, smc={smc_count}"
                    )
            except Exception as exc:
                failures.append(f"indicators {stock['market']} {stock['stock_id']}: {exc}")
                logger.exception("還原行情或指標重算失敗：%s %s", stock["market"], stock["stock_id"])

    logger.info("本次行情更新成功 %s 檔；失敗 %s 檔", len(refreshed_this_run), len(failures))
    if failures:
        raise RuntimeError("部分股票更新失敗：\n" + "\n".join(failures[:30]))


if __name__ == "__main__":
    main()
