"""Calculate SMC heuristics from Neon daily_prices and upsert daily_smc."""
from __future__ import annotations
import argparse
import logging
import os
import psycopg
from psycopg.rows import dict_row
from smc_indicators import compute_smc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

UPSERT_SQL = """
INSERT INTO daily_smc (
 market, stock_id, trade_date, swing_high, swing_low,
 bos_bullish, bos_bearish, choch_bullish, choch_bearish, trend_direction,
 liquidity_sweep_high, liquidity_sweep_low, order_block_type,
 order_block_high, order_block_low, fvg_type, fvg_high, fvg_low
) VALUES (
 %(market)s, %(stock_id)s, %(trade_date)s, %(swing_high)s, %(swing_low)s,
 %(bos_bullish)s, %(bos_bearish)s, %(choch_bullish)s, %(choch_bearish)s, %(trend_direction)s,
 %(liquidity_sweep_high)s, %(liquidity_sweep_low)s, %(order_block_type)s,
 %(order_block_high)s, %(order_block_low)s, %(fvg_type)s, %(fvg_high)s, %(fvg_low)s
)
ON CONFLICT (market, stock_id, trade_date) DO UPDATE SET
 swing_high=EXCLUDED.swing_high, swing_low=EXCLUDED.swing_low,
 bos_bullish=EXCLUDED.bos_bullish, bos_bearish=EXCLUDED.bos_bearish,
 choch_bullish=EXCLUDED.choch_bullish, choch_bearish=EXCLUDED.choch_bearish,
 trend_direction=EXCLUDED.trend_direction,
 liquidity_sweep_high=EXCLUDED.liquidity_sweep_high,
 liquidity_sweep_low=EXCLUDED.liquidity_sweep_low,
 order_block_type=EXCLUDED.order_block_type,
 order_block_high=EXCLUDED.order_block_high, order_block_low=EXCLUDED.order_block_low,
 fvg_type=EXCLUDED.fvg_type, fvg_high=EXCLUDED.fvg_high, fvg_low=EXCLUDED.fvg_low,
 calculated_at=NOW()
"""

def calculate_stock(conn, market: str, stock_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute("""SELECT market, stock_id, trade_date, open, high, low, close
                       FROM daily_adjusted_prices WHERE market=%s AND stock_id=%s
                         AND NOT EXISTS (SELECT 1 FROM public.model_stock_exclusions x
                          WHERE x.market=daily_adjusted_prices.market AND x.stock_id=daily_adjusted_prices.stock_id)
                       ORDER BY trade_date""",
                    (market, stock_id))
        rows = cur.fetchall()
    if not rows:
        logger.warning("沒有行情資料：%s %s", market, stock_id)
        return 0
    calculated = compute_smc(rows)
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(UPSERT_SQL, calculated)
    logger.info("%s %s：寫入 %s 筆 SMC", market.upper(), stock_id, len(calculated))
    return len(calculated)

def main():
    parser = argparse.ArgumentParser(description="計算 BOS、CHOCH、Order Block、FVG、Liquidity Sweep")
    parser.add_argument("--market", choices=("twse","tpex","both"), default="both")
    parser.add_argument("--stock-id")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    if args.offset < 0 or not 1 <= args.limit <= 20:
        parser.error("offset 必須 >= 0，limit 必須介於 1 到 20")
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("請設定 DATABASE_URL；不可將資料庫密碼提交到 Git")
    markets = ("twse","tpex") if args.market == "both" else (args.market,)
    with psycopg.connect(url, row_factory=dict_row, connect_timeout=20) as conn:
        with conn.cursor() as cur:
            if args.stock_id:
                cur.execute("""SELECT DISTINCT market, stock_id FROM daily_adjusted_prices
                               WHERE market=ANY(%s) AND stock_id=%s
                                 AND NOT EXISTS (SELECT 1 FROM public.model_stock_exclusions x WHERE x.market=daily_adjusted_prices.market AND x.stock_id=daily_adjusted_prices.stock_id)
                               ORDER BY market,stock_id""",
                            (list(markets), args.stock_id))
                stocks = cur.fetchall()
            else:
                stocks = []
                for market in markets:
                    cur.execute("""SELECT DISTINCT market, stock_id FROM daily_adjusted_prices
                                   WHERE market=%s AND NOT EXISTS (SELECT 1 FROM public.model_stock_exclusions x WHERE x.market=daily_adjusted_prices.market AND x.stock_id=daily_adjusted_prices.stock_id) ORDER BY stock_id OFFSET %s LIMIT %s""",
                                (market,args.offset,args.limit))
                    stocks.extend(cur.fetchall())
        if not stocks:
            raise RuntimeError("找不到符合條件的股票行情資料")
        total = sum(calculate_stock(conn, s["market"], s["stock_id"]) for s in stocks)
    logger.info("SMC 計算完成：%s 筆", total)

if __name__ == "__main__":
    main()
