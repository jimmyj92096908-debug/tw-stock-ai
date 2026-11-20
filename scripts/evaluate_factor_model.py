"""Read-only research evaluation of the already-defined composite factor model.

Requires DATABASE_URL configured as an intentionally read-only DB role.
Never issues INSERT/UPDATE/DELETE, does not send LINE messages, never stores
individual stock or user records in evidence. Default sample: 180 days.
"""
from __future__ import annotations
import argparse
from datetime import date, timedelta
import json
import os
from pathlib import Path
import sys

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from factor_model_validation import EVALUATION_SQL, evaluate_rows


def evaluate_database(database_url, start: date, end: date):
    if not database_url:
        raise ValueError("DATABASE_URL required")
    if start > end or (end-start).days > 366:
        raise ValueError("evaluation period must be 0..366 days")
    # Explicit session-level read-only; no permanent server mutation.
    with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=20) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(EVALUATION_SQL, (0.50, start, end))
                return evaluate_rows(cur.fetchall())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=date.fromisoformat,
                   default=date.today()-timedelta(days=180))
    p.add_argument("--end", type=date.fromisoformat, default=date.today())
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    result = evaluate_database(os.getenv("DATABASE_URL", ""), args.start, args.end)
    # Aggregates only; no SQL credentials or personal information.
    report = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report)


if __name__ == "__main__":
    main()
