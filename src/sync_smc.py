"""Calculate confirmed SMC structure and upsert daily summaries into Neon.

The script only writes to the existing public.daily_smc table. It does not
change the schema or write the append-only public.smc_events table.
"""
from __future__ import annotations

import os
from collections import defaultdict
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row

try:
    from .smc import compute_smc
except ImportError:  # Running as: python sync_smc.py from the src directory.
    from smc import compute_smc


UPSERT_SQL = """
INSERT INTO public.daily_smc (
    market, stock_id, trade_date, swing_high, swing_low,
    bos_bullish, bos_bearish, choch_bullish, choch_bearish,
    trend_direction, liquidity_sweep_high, liquidity_sweep_low,
    order_block_type, order_block_high, order_block_low,
    fvg_type, fvg_high, fvg_low, calculated_at
)
VALUES (
    %(market)s, %(stock_id)s, %(trade_date)s, %(swing_high)s, %(swing_low)s,
    %(bos_bullish)s, %(bos_bearish)s, %(choch_bullish)s, %(choch_bearish)s,
    %(trend_direction)s, %(liquidity_sweep_high)s, %(liquidity_sweep_low)s,
    %(order_block_type)s, %(order_block_high)s, %(order_block_low)s,
    %(fvg_type)s, %(fvg_high)s, %(fvg_low)s, NOW()
)
ON CONFLICT (market, stock_id, trade_date) DO UPDATE SET
    swing_high = EXCLUDED.swing_high,
    swing_low = EXCLUDED.swing_low,
    bos_bullish = EXCLUDED.bos_bullish,
    bos_bearish = EXCLUDED.bos_bearish,
    choch_bullish = EXCLUDED.choch_bullish,
    choch_bearish = EXCLUDED.choch_bearish,
    trend_direction = EXCLUDED.trend_direction,
    liquidity_sweep_high = EXCLUDED.liquidity_sweep_high,
    liquidity_sweep_low = EXCLUDED.liquidity_sweep_low,
    order_block_type = EXCLUDED.order_block_type,
    order_block_high = EXCLUDED.order_block_high,
    order_block_low = EXCLUDED.order_block_low,
    fvg_type = EXCLUDED.fvg_type,
    fvg_high = EXCLUDED.fvg_high,
    fvg_low = EXCLUDED.fvg_low,
    calculated_at = NOW()
"""


def build_daily_smc_records(
    rows: Iterable[dict[str, Any]],
    pivot_left: int = 3,
    pivot_right: int = 3,
    ob_lookback: int = 10,
) -> list[dict[str, Any]]:
    """Convert one stock's chronological OHLC rows to daily_smc table records."""
    daily = compute_smc(
        rows,
        pivot_left=pivot_left,
        pivot_right=pivot_right,
        ob_lookback=ob_lookback,
    )
    records = []
    for day in daily:
        record = {
            "market": day["market"],
            "stock_id": day["stock_id"],
            "trade_date": day["trade_date"],
            "swing_high": None,
            "swing_low": None,
            "bos_bullish": False,
            "bos_bearish": False,
            "choch_bullish": False,
            "choch_bearish": False,
            "trend_direction": {"bullish": 1, "bearish": -1, "neutral": 0}[day["structure_trend"]],
            "liquidity_sweep_high": False,
            "liquidity_sweep_low": False,
            "order_block_type": None,
            "order_block_high": None,
            "order_block_low": None,
            "fvg_type": None,
            "fvg_high": None,
            "fvg_low": None,
        }
        for event in day["events"]:
            event_type = event["type"]
            if event_type == "swing_high_confirmed":
                record["swing_high"] = event["price"]
            elif event_type == "swing_low_confirmed":
                record["swing_low"] = event["price"]
            elif event_type == "bos":
                record["bos_bullish" if event["direction"] == "bullish" else "bos_bearish"] = True
            elif event_type == "choch":
                record["choch_bullish" if event["direction"] == "bullish" else "choch_bearish"] = True
            elif event_type == "buy_side_liquidity_sweep":
                record["liquidity_sweep_high"] = True
            elif event_type == "sell_side_liquidity_sweep":
                record["liquidity_sweep_low"] = True
            elif event_type in ("bullish_fvg", "bearish_fvg") and record["fvg_type"] is None:
                record["fvg_type"] = "bullish" if event_type == "bullish_fvg" else "bearish"
                record["fvg_low"] = event["lower"]
                record["fvg_high"] = event["upper"]

            order_block = event.get("order_block")
            if order_block is not None and record["order_block_type"] is None:
                record["order_block_type"] = event["direction"]
                record["order_block_high"] = order_block["high"]
                record["order_block_low"] = order_block["low"]

        records.append(record)
    return records


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL 未設定，停止執行。")

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    with psycopg.connect(database_url, connect_timeout=20, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT market, stock_id, trade_date, open, high, low, close
            FROM public.daily_prices
            ORDER BY market, stock_id, trade_date
            """
        ).fetchall()
        if not rows:
            raise RuntimeError("daily_prices 沒有任何日 K 資料，停止執行。")

        for row in rows:
            grouped[(row["market"], str(row["stock_id"]))].append({
                "market": row["market"],
                "stock_id": str(row["stock_id"]),
                "trade_date": row["trade_date"].isoformat(),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
            })

        records = []
        for bars in grouped.values():
            records.extend(build_daily_smc_records(bars))

        if len(records) != len(rows):
            raise RuntimeError(
                f"計算筆數不符：行情 {len(rows)} 筆，SMC {len(records)} 筆。"
            )

        with conn.transaction():
            with conn.cursor() as cur:
                for start in range(0, len(records), 1000):
                    cur.executemany(UPSERT_SQL, records[start:start + 1000])

    print(f"Stocks processed: {len(grouped)}")
    print(f"Daily price rows read: {len(rows)}")
    print(f"Daily SMC rows upserted: {len(records)}")
    print("Target: public.daily_smc (existing schema; no DDL executed)")


if __name__ == "__main__":
    main()
