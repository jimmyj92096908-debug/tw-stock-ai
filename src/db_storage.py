"""將 TWSE／TPEx CSV 歷史日 K 安全寫入 PostgreSQL（Neon）。

需要環境變數 DATABASE_URL。此模組不包含、也不讀取任何硬編碼密碼。
TPEx 個股日成交資訊原始 CSV 成交仟股／仟元僅於標記來源下轉換為股／元。
此匯入器一律只新增缺漏主鍵，不覆寫正式資料庫既有行情。
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
from pathlib import Path
from decimal import Decimal, InvalidOperation
from typing import Any

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HISTORY_DIR = ROOT / "data" / "history"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

INSERT_MISSING_PRICE_SQL = """
INSERT INTO daily_prices (
    market, stock_id, trade_date, open, high, low, close,
    volume, turnover, price_change, transactions, source
)
VALUES (
    %(market)s, %(stock_id)s, %(trade_date)s, %(open)s, %(high)s, %(low)s, %(close)s,
    %(volume)s, %(turnover)s, %(change)s, %(transactions)s, %(source)s
)
ON CONFLICT (market, stock_id, trade_date) DO NOTHING
"""


def optional_number(value: Any) -> int | float | None:
    if value is None:
        return None
    raw = str(value).strip().replace(",", "")
    if raw in {"", "--", "---", "None", "null"}:
        return None
    number = float(raw)
    return int(number) if number.is_integer() else number


def normalize_tpex_monthly_units(parsed: dict[str, Any]) -> dict[str, Any]:
    """Convert raw TPEx tradingStock thousands to shares/NTD exactly once.

    Only the raw monthly CSV source tag is supported; the OpenAPI already
    reports shares/NTD and must never be scaled. No existing DB row is changed.
    """
    if parsed["market"] != "tpex" or parsed["source"] != "TPEX_TRADING_STOCK":
        return parsed

    for key in ("volume", "turnover"):
        value = parsed[key]
        if value is None:
            continue
        try:
            scaled = Decimal(str(value)) * 1000
        except InvalidOperation as exc:
            raise ValueError(f"Invalid raw TPEx {key}") from exc
        if not scaled.is_finite() or scaled < 0:
            raise ValueError(f"Invalid raw TPEx {key}")
        if key == "volume":
            if scaled != scaled.to_integral_value() or scaled > 9223372036854775807:
                raise ValueError("TPEx volume cannot be represented as integer shares")
            parsed[key] = int(scaled)
        else:
            parsed[key] = scaled
    parsed["source"] = "TPEX_TRADING_STOCK_NORMALIZED"
    return parsed


def read_history_csv(path: Path, market: str) -> list[dict[str, Any]]:
    """讀取並驗證單檔歷史日 K CSV。"""
    if market not in {"twse", "tpex"}:
        raise ValueError(f"Unsupported market: {market}")

    with path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        required = {
            "stock_id", "trade_date", "open", "high", "low", "close",
            "volume", "turnover", "change", "transactions", "source",
        }
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError(f"{path} missing columns: {sorted(required - set(reader.fieldnames or []))}")

        rows = []
        for row in reader:
            if not row.get("trade_date") or not row.get("stock_id"):
                continue
            parsed = {
                "market": market,
                "stock_id": row["stock_id"].strip(),
                "trade_date": row["trade_date"].strip(),
                "open": optional_number(row.get("open")),
                "high": optional_number(row.get("high")),
                "low": optional_number(row.get("low")),
                "close": optional_number(row.get("close")),
                "volume": optional_number(row.get("volume")),
                "turnover": optional_number(row.get("turnover")),
                "change": optional_number(row.get("change")),
                "transactions": optional_number(row.get("transactions")),
                "source": row.get("source") or market.upper(),
            }
            parsed = normalize_tpex_monthly_units(parsed)
            prices = [parsed[key] for key in ("open", "high", "low", "close") if parsed[key] is not None]
            high, low = parsed["high"], parsed["low"]
            if prices and (
                (high is not None and low is not None and high < low)
                or (low is not None and any(value < low for value in prices))
                or (high is not None and any(value > high for value in prices))
            ):
                raise ValueError(
                    f"Invalid OHLC in {path}: {parsed['stock_id']} "
                    f"{parsed['trade_date']} {prices}"
                )
            rows.append(parsed)
    return rows


def upsert_csv(conn: psycopg.Connection, path: Path, market: str) -> int:
    rows = read_history_csv(path, market)
    if not rows:
        logger.warning("略過空檔案：%s", path)
        return 0

    stock_id = rows[0]["stock_id"]
    if any(row["stock_id"] != stock_id for row in rows):
        raise ValueError(f"CSV contains more than one stock ID: {path}")

    run_id = None
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO stock_master (market, stock_id)
                    VALUES (%s, %s)
                    ON CONFLICT (market, stock_id) DO NOTHING
                    """,
                    (market, stock_id),
                )
                cur.execute(
                    """
                    INSERT INTO import_runs (market, stock_id, rows_received, status)
                    VALUES (%s, %s, %s, 'running')
                    RETURNING run_id
                    """,
                    (market, stock_id, len(rows)),
                )
                run_id = cur.fetchone()["run_id"]
                cur.executemany(INSERT_MISSING_PRICE_SQL, rows)
                # psycopg3 executemany rowcount is the cumulative affected-row
                # count, so ON CONFLICT DO NOTHING contributes zero.
                inserted = cur.rowcount
                if not 0 <= inserted <= len(rows):
                    raise RuntimeError("Unexpected history insert row count")
                cur.execute(
                    """
                    UPDATE import_runs
                    SET finished_at = NOW(), rows_upserted = %s, status = 'success'
                    WHERE run_id = %s
                    """,
                    (inserted, run_id),
                )
        logger.info("%s %s：新增 %s / 收到 %s 筆", market.upper(), stock_id, inserted, len(rows))
        return inserted
    except Exception as exc:
        if run_id is not None:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE import_runs
                        SET finished_at = NOW(), status = 'failed', error_message = %s
                        WHERE run_id = %s
                        """,
                        (str(exc)[:2000], run_id),
                    )
        raise


def import_history(history_dir: Path) -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set. Add it as a GitHub Actions secret; never commit it.")

    total = 0
    with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=20) as conn:
        for market in ("twse", "tpex"):
            market_dir = history_dir / market
            if not market_dir.exists():
                logger.info("沒有 %s 資料夾，略過", market)
                continue
            for path in sorted(market_dir.glob("*.csv")):
                total += upsert_csv(conn, path, market)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="匯入上市／上櫃 CSV 歷史行情至 PostgreSQL")
    parser.add_argument("--history-dir", type=Path, default=DEFAULT_HISTORY_DIR)
    args = parser.parse_args()
    count = import_history(args.history_dir)
    logger.info("資料庫匯入完成：共處理 %s 筆日 K", count)


if __name__ == "__main__":
    main()
