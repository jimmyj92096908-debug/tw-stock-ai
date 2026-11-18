"""從 Neon daily_prices 計算並同步九均線、RSI14、成交量均線與 ATR14。

只寫入既有 daily_technicals 表，不變更資料庫結構。
執行前需設定 DATABASE_URL。預設處理所有已有日 K 的股票。
"""
from __future__ import annotations

import os
from collections import defaultdict

import psycopg
from psycopg.rows import dict_row

from technical_indicators import compute_indicators

UPSERT_SQL = """
INSERT INTO daily_technicals (
    market, stock_id, trade_date,
    ma5, ma10, ma13, ma20, ma34, ma55, ma60, ma120, ma240,
    rsi14, volume_ma5, volume_ma20, atr14
)
VALUES (
    %(market)s, %(stock_id)s, %(trade_date)s,
    %(ma5)s, %(ma10)s, %(ma13)s, %(ma20)s, %(ma34)s,
    %(ma55)s, %(ma60)s, %(ma120)s, %(ma240)s,
    %(rsi14)s, %(volume_ma5)s, %(volume_ma20)s, %(atr14)s
)
ON CONFLICT (market, stock_id, trade_date) DO UPDATE SET
    ma5 = EXCLUDED.ma5,
    ma10 = EXCLUDED.ma10,
    ma13 = EXCLUDED.ma13,
    ma20 = EXCLUDED.ma20,
    ma34 = EXCLUDED.ma34,
    ma55 = EXCLUDED.ma55,
    ma60 = EXCLUDED.ma60,
    ma120 = EXCLUDED.ma120,
    ma240 = EXCLUDED.ma240,
    rsi14 = EXCLUDED.rsi14,
    volume_ma5 = EXCLUDED.volume_ma5,
    volume_ma20 = EXCLUDED.volume_ma20,
    atr14 = EXCLUDED.atr14,
    calculated_at = NOW()
"""


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL 未設定，停止執行。")

    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    with psycopg.connect(database_url, connect_timeout=20, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT market, stock_id, trade_date, high, low, close, volume
            FROM daily_prices
            ORDER BY market, stock_id, trade_date
            """
        ).fetchall()

        if not rows:
            raise RuntimeError("daily_prices 沒有任何日 K 資料，停止寫入。")

        for row in rows:
            grouped[(row["market"], str(row["stock_id"]))].append({
                "market": row["market"],
                "stock_id": str(row["stock_id"]),
                "trade_date": row["trade_date"].isoformat(),
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
            })

        records = []
        for (market, stock_id), bars in grouped.items():
            records.extend(compute_indicators(bars))

        if len(records) != len(rows):
            raise RuntimeError(
                f"計算筆數不符：行情 {len(rows)} 筆，指標 {len(records)} 筆。"
            )

        with conn.transaction():
            with conn.cursor() as cur:
                for start in range(0, len(records), 1000):
                    cur.executemany(UPSERT_SQL, records[start:start + 1000])

    print(f"Stocks processed: {len(grouped)}")
    print(f"Daily price rows read: {len(rows)}")
    print(f"Technical indicator rows upserted: {len(records)}")


if __name__ == "__main__":
    main()
