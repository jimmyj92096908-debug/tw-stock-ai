"""Read existing daily technicals + SMC and upsert explainable composite scores."""
from __future__ import annotations

import json
import os


UPSERT_SQL = """
INSERT INTO public.daily_composite_scores (
    market, stock_id, as_of_date, total_score, coverage_weight,
    technical_score, smc_score, chip_score, component_status,
    short_term_score, swing_score, long_term_score,
    short_coverage, swing_coverage, long_coverage, calculated_at
) VALUES (
    %(market)s, %(stock_id)s, %(trade_date)s, %(total_score)s, %(coverage_weight)s,
    %(technical_score)s, %(smc_score)s, %(chip_score)s, %(component_status)s::jsonb,
    %(short_term_score)s, %(swing_score)s, %(long_term_score)s,
    %(short_coverage)s, %(swing_coverage)s, %(long_coverage)s, NOW()
)
ON CONFLICT (market, stock_id, as_of_date) DO UPDATE SET
    total_score = EXCLUDED.total_score,
    coverage_weight = EXCLUDED.coverage_weight,
    technical_score = EXCLUDED.technical_score,
    smc_score = EXCLUDED.smc_score,
    chip_score = EXCLUDED.chip_score,
    component_status = EXCLUDED.component_status,
    short_term_score = EXCLUDED.short_term_score,
    swing_score = EXCLUDED.swing_score,
    long_term_score = EXCLUDED.long_term_score,
    short_coverage = EXCLUDED.short_coverage,
    swing_coverage = EXCLUDED.swing_coverage,
    long_coverage = EXCLUDED.long_coverage,
    calculated_at = NOW()
"""


def build_score_record(row):
    try:
        from .composite_scoring import compute_composite_score
    except ImportError:
        from composite_scoring import compute_composite_score
    result = compute_composite_score(row)
    return {
        "market": row["market"],
        "stock_id": str(row["stock_id"]),
        "trade_date": row["trade_date"],
        **result,
        "component_status": json.dumps(result["component_status"]),
    }


def main():
    import psycopg
    from psycopg.rows import dict_row

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL 未設定，停止執行。")

    sql = """
    SELECT p.market, p.stock_id, p.trade_date, p.close, p.volume,
           t.ma5, t.ma10, t.ma13, t.ma20, t.ma34, t.ma55, t.ma60,
           t.ma120, t.ma240, t.rsi14, t.volume_ma20, t.atr14,
           s.bos_bullish, s.bos_bearish, s.choch_bullish, s.choch_bearish,
           s.trend_direction, s.liquidity_sweep_high, s.liquidity_sweep_low,
           s.order_block_type, s.fvg_type
    FROM public.daily_prices p
    LEFT JOIN public.daily_technicals t
      USING (market, stock_id, trade_date)
    LEFT JOIN public.daily_smc s
      USING (market, stock_id, trade_date)
    ORDER BY p.market, p.stock_id, p.trade_date
    """
    with psycopg.connect(database_url, connect_timeout=20, row_factory=dict_row) as conn:
        rows = conn.execute(sql).fetchall()
        if not rows:
            raise RuntimeError("沒有可評分的 daily_prices 資料。")
        records = [build_score_record(row) for row in rows]
        if len(records) != len(rows):
            raise RuntimeError("評分筆數與行情筆數不一致。")
        with conn.transaction():
            with conn.cursor() as cur:
                for start in range(0, len(records), 1000):
                    cur.executemany(UPSERT_SQL, records[start:start + 1000])
    print(f"Daily rows scored: {len(rows)}")
    print(f"Composite score rows upserted: {len(records)}")
    print("Target: public.daily_composite_scores (existing schema; no DDL executed)")


if __name__ == "__main__":
    main()
