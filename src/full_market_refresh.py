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


def shift_month(value: date, offset: int) -> date:
    """Move a first-of-month date by a bounded integer month offset."""
    total = value.year * 12 + value.month - 1 + offset
    return date(total // 12, total % 12 + 1, 1)


def plan_download_windows(stock: dict, today: date, *, archive_months: int = 3) -> list[tuple[date, date]]:
    """Bound archived history to small windows while refreshing the current month.

    Full-market snapshots can populate one trading day without the historical
    bars needed for moving averages. Use the *earliest* existing valid bar to
    progressively extend backwards, at most 3 archive months per rotation.
    Never request five years of data in a single stock invocation.
    """
    if not 1 <= archive_months <= 6:
        raise ValueError("archive_months must be 1..6")
    current = month_start(today)
    floor = shift_month(current, -60)
    oldest = stock.get("earliest_trade_date")
    newest = stock.get("latest_trade_date")
    windows = []
    if oldest is None:
        windows.append((shift_month(current, -archive_months + 1), current))
        return windows

    first = month_start(oldest)
    if first > floor:
        archive_end = previous_month(first)
        if archive_end >= floor:
            windows.append((
                max(floor, shift_month(archive_end, -(archive_months - 1))),
                archive_end,
            ))

    # Monthly sources update late: refetch the preceding month if the
    # stock itself has not had a valid close since that month's beginning.
    recent_start = previous_month(today) if newest is None or newest < current else current
    windows.append((recent_start, current))
    return windows


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
                       MIN(dp.trade_date) FILTER (
                           WHERE dp.close IS NOT NULL
                       ) AS earliest_trade_date,
                       st.last_attempt_at
                FROM stock_master sm
                LEFT JOIN daily_prices dp
                  ON dp.market=sm.market AND dp.stock_id=sm.stock_id
                LEFT JOIN market_data_refresh_state st
                  ON st.market=sm.market AND st.stock_id=sm.stock_id
                WHERE sm.market=%s
                GROUP BY sm.market, sm.stock_id, sm.stock_name, st.last_attempt_at
            ), numbered AS (
                SELECT market,stock_id,stock_name,latest_trade_date,earliest_trade_date,
                       ROW_NUMBER() OVER (
                           PARTITION BY (latest_trade_date IS NULL)
                           ORDER BY last_attempt_at ASC NULLS FIRST,
                                    latest_trade_date ASC NULLS FIRST, stock_id
                       ) AS rotation_slot
                FROM candidates
            )
            SELECT market,stock_id,stock_name,latest_trade_date,earliest_trade_date
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


def classify_price_refresh(downloaded: int, latest_trade_date: date | None) -> str:
    """Separate expected no-data symbols from invalid imports and usable prices.

    An exchange may return no records for suspended or newly listed symbols.
    Such an empty result must not be reported as a successful refresh or
    passed to adjusted-bar/indicator calculations. If data was downloaded
    but none made it into daily_prices, treat that as a genuine error.
    """
    if downloaded < 0:
        raise ValueError("Downloaded row count cannot be negative")
    if latest_trade_date is not None:
        return "usable"
    if downloaded == 0:
        return "no_data"
    return "invalid_import"


def refresh_one(conn: psycopg.Connection, stock: dict, today: date) -> bool:
    market, stock_id = stock["market"], stock["stock_id"]
    windows = plan_download_windows(stock, today)
    module = market_data if market == "twse" else tpex_market_data
    logger.info(
        "更新 %s %s：%s",
        market.upper(), stock_id,
        ", ".join(f"{start:%Y-%m}..{end:%Y-%m}" for start,end in windows),
    )
    try:
        count = 0
        for start,end in windows:
            count += module.download_range(
                stock_id, start.year, end.year, start.month, end.month
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
        outcome = classify_price_refresh(count, latest)
        if outcome == "no_data":
            # Mark the missing history explicitly; keep rotating the market.
            # This is a data-availability condition, not an indicator failure.
            record_attempt(
                conn, market, stock_id, "failed", 0, None,
                "官方歷史行情無有效價格資料；本次略過還原行情與技術指標",
            )
            logger.warning(
                "%s %s 官方歷史行情無有效價格資料；略過後續指標，保留重試紀錄",
                market, stock_id,
            )
            return False
        if outcome == "invalid_import":
            raise RuntimeError("下載有資料但未成功寫入任何有效行情，需排查匯入問題")
        record_attempt(conn, market, stock_id, "success", count, latest)
        logger.info("%s %s 更新成功：本次取得 %s 筆；最新交易日 %s", market, stock_id, count, latest)
        return True
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
    unavailable_this_run: list[dict[str, str]] = []
    refreshed_this_run: list[dict[str, str]] = []
    with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=20) as conn:
        upsert_universe(conn, universe)
        for market in ("twse", "tpex"):
            batch = select_batch(conn, market, batch_size)
            logger.info("%s 本次輪替選取 %s 檔", market.upper(), len(batch))
            for index, stock in enumerate(batch):
                try:
                    has_valid_prices = refresh_one(conn, stock, today)
                    if has_valid_prices:
                        refreshed_this_run.append({"market": market, "stock_id": stock["stock_id"]})
                    else:
                        unavailable_this_run.append({"market": market, "stock_id": stock["stock_id"]})
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

    logger.info(
        "本次行情更新成功 %s 檔；無有效行情略過 %s 檔；真正失敗 %s 檔",
        len(refreshed_this_run), len(unavailable_this_run), len(failures),
    )
    if failures:
        raise RuntimeError("部分股票更新失敗：\n" + "\n".join(failures[:30]))


if __name__ == "__main__":
    main()
