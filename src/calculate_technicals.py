"""讀取 Neon daily_prices，計算技術指標並寫入 daily_technicals。"""
from __future__ import annotations

import argparse
import logging
import os

import psycopg
from psycopg.rows import dict_row

from technical_indicators import compute_indicators

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

UPSERT_SQL = """
INSERT INTO daily_technicals (
    market, stock_id, trade_date,
    ma5, ma10, ma13, ma20, ma34, ma55, ma60, ma120, ma240,
    rsi14, volume_ma5, volume_ma20, atr14
) VALUES (
    %(market)s, %(stock_id)s, %(trade_date)s,
    %(ma5)s, %(ma10)s, %(ma13)s, %(ma20)s, %(ma34)s, %(ma55)s,
    %(ma60)s, %(ma120)s, %(ma240)s,
    %(rsi14)s, %(volume_ma5)s, %(volume_ma20)s, %(atr14)s
)
ON CONFLICT (market, stock_id, trade_date) DO UPDATE SET
    ma5=EXCLUDED.ma5, ma10=EXCLUDED.ma10, ma13=EXCLUDED.ma13,
    ma20=EXCLUDED.ma20, ma34=EXCLUDED.ma34, ma55=EXCLUDED.ma55,
    ma60=EXCLUDED.ma60, ma120=EXCLUDED.ma120, ma240=EXCLUDED.ma240,
    rsi14=EXCLUDED.rsi14, volume_ma5=EXCLUDED.volume_ma5,
    volume_ma20=EXCLUDED.volume_ma20, atr14=EXCLUDED.atr14,
    calculated_at=NOW()
"""


def calculate_stock(conn: psycopg.Connection, market: str, stock_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT market, stock_id, trade_date, high, low, close, volume
            FROM daily_prices
            WHERE market=%s AND stock_id=%s
            ORDER BY trade_date
            """,
            (market, stock_id),
        )
        rows = cur.fetchall()

    if not rows:
        logger.warning("沒有行情資料：%s %s", market, stock_id)
        return 0

    calculated = compute_indicators(rows)
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(UPSERT_SQL, calculated)
    logger.info("%s %s：計算並寫入 %s 個交易日", market.upper(), stock_id, len(calculated))
    return len(calculated)


def main() -> None:
    parser = argparse.ArgumentParser(description="計算九均線、RSI14、量均線及 ATR14")
    parser.add_argument("--market", choices=("twse", "tpex", "both"), default="both")
    parser.add_argument("--stock-id", help="只計算指定股票")
    parser.add_argument("--offset", type=int, default=0, help="股票清單起始位移")
    parser.add_argument("--limit", type=int, default=5, help="本次最多計算幾檔；預設 5 檔")
    args = parser.parse_args()
    if args.offset < 0 or not 1 <= args.limit <= 20:
        parser.error("offset 必須 >= 0，limit 必須介於 1 到 20。")

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("請設定 DATABASE_URL 環境變數；不要將資料庫密碼寫入程式或提交至 Git。")

    markets = ("twse", "tpex") if args.market == "both" else (args.market,)
    with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=20) as conn:
        with conn.cursor() as cur:
            if args.stock_id:
                cur.execute(
                    "SELECT DISTINCT market, stock_id FROM daily_prices WHERE market = ANY(%s) AND stock_id=%s ORDER BY market, stock_id",
                    (list(markets), args.stock_id),
                )
                stocks = cur.fetchall()
            else:
                stocks = []
                for market in markets:
                    cur.execute(
                        """
                        SELECT DISTINCT market, stock_id
                        FROM daily_prices
                        WHERE market = %s
                        ORDER BY stock_id
                        OFFSET %s LIMIT %s
                        """,
                        (market, args.offset, args.limit),
                    )
                    stocks.extend(cur.fetchall())
        if not stocks:
            raise RuntimeError("本批沒有找到符合條件的股票；請檢查市場、offset 與資料庫行情資料。")

        total = 0
        for stock in stocks:
            total += calculate_stock(conn, stock["market"], stock["stock_id"])
    logger.info("技術指標計算完成：%s 筆", total)


if __name__ == "__main__":
    main()
