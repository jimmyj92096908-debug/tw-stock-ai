"""Record verified historical backfill progress in Neon."""

from __future__ import annotations

import argparse
import csv
import os
from datetime import date
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", required=True, type=date.fromisoformat)
    parser.add_argument("--end-date", required=True, type=date.fromisoformat)
    args = parser.parse_args()
    if args.start_date > args.end_date:
        parser.error("start-date must be <= end-date")

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured.")
    run_id = os.environ.get("GITHUB_RUN_ID")

    summary_path = ROOT / "data" / "history" / "batch_summary.csv"
    with summary_path.open(newline="", encoding="utf-8-sig") as f:
        jobs = list(csv.DictReader(f))
    if not jobs:
        raise RuntimeError("Batch summary is empty; refusing to record progress.")

    recorded = 0
    with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=20) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                for item in jobs:
                    market = "twse" if item["market"] == "上市" else "tpex"
                    stock_id = item["stock_id"]
                    cur.execute(
                        """SELECT COUNT(*) AS n, MIN(trade_date) AS first_date,
                                  MAX(trade_date) AS last_date
                           FROM daily_prices
                           WHERE market=%s AND stock_id=%s
                             AND trade_date >= %s AND trade_date <= %s""",
                        (market, stock_id, args.start_date, args.end_date),
                    )
                    result = cur.fetchone()
                    if result["n"] <= 0:
                        raise RuntimeError(
                            f"Neon verification failed for {market} {stock_id}; "
                            "progress was not recorded."
                        )
                    cur.execute(
                        """INSERT INTO backfill_progress (
                               market, stock_id, start_date, end_date, status,
                               rows_downloaded, first_trade_date, last_trade_date,
                               finished_at, github_run_id, error_message, updated_at
                           )
                           VALUES (%s, %s, %s, %s, 'success', %s, %s, %s,
                                   NOW(), %s, NULL, NOW())
                           ON CONFLICT (market, stock_id, start_date, end_date)
                           DO UPDATE SET
                               status='success',
                               rows_downloaded=EXCLUDED.rows_downloaded,
                               first_trade_date=EXCLUDED.first_trade_date,
                               last_trade_date=EXCLUDED.last_trade_date,
                               finished_at=NOW(),
                               github_run_id=EXCLUDED.github_run_id,
                               error_message=NULL,
                               updated_at=NOW()""",
                        (
                            market, stock_id, args.start_date, args.end_date,
                            result["n"], result["first_date"], result["last_date"],
                            run_id,
                        ),
                    )
                    recorded += 1
                    print(
                        f"進度已記錄：{market} {stock_id}，{result['n']} 筆，"
                        f"{result['first_date']} 至 {result['last_date']}"
                    )
    print(f"完成：已驗證並記錄 {recorded} 檔股票。")


if __name__ == "__main__":
    main()
