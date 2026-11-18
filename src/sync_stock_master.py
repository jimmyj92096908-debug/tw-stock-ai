"""Synchronize the official TWSE/TPEx stock list into Neon stock_master."""

from __future__ import annotations

import csv
import os
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "stock_list.csv"


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured.")

    if not CSV_PATH.exists():
        raise FileNotFoundError(CSV_PATH)

    with CSV_PATH.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    if not rows:
        raise RuntimeError("Official stock list is empty; refusing to modify stock_master.")

    values = []
    for row in rows:
        market_name = row["market"].strip()
        market = {"上市": "twse", "上櫃": "tpex"}.get(market_name)
        stock_id = row["stock_id"].strip()
        if market is None or not stock_id.isdigit():
            continue
        values.append((market, stock_id, row.get("stock_name", "").strip(),
                       row.get("industry", "").strip()))

    if not values:
        raise RuntimeError("No valid TWSE/TPEx common stock records found.")

    inserted = 0
    updated = 0
    with psycopg.connect(database_url, connect_timeout=20) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                for market, stock_id, name, industry in values:
                    cur.execute(
                        """
                        INSERT INTO stock_master (market, stock_id, stock_name, industry)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (market, stock_id) DO UPDATE
                        SET stock_name = EXCLUDED.stock_name,
                            industry = EXCLUDED.industry,
                            updated_at = NOW()
                        RETURNING (xmax = 0) AS inserted
                        """,
                        (market, stock_id, name, industry),
                    )
                    if cur.fetchone()[0]:
                        inserted += 1
                    else:
                        updated += 1

    print(f"Official stock list synchronized: {len(values)} records")
    print(f"New stocks inserted: {inserted}; existing stocks refreshed: {updated}")


if __name__ == "__main__":
    main()
