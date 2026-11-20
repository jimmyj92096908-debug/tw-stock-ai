"""Read-only adjusted-price holdout evaluation (research only)."""
from __future__ import annotations
import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from factor_model_v2 import ADJUSTED_EVALUATION_SQL, evaluate_adjusted


def run(database_url, *, start, end, holdout_start, cost_bps=30):
    if not database_url:
        raise ValueError("DATABASE_URL required")
    if not start<=holdout_start<=end or (end-start).days>366:
        raise ValueError("Invalid 0..366-day evaluation and holdout dates")
    with psycopg.connect(database_url,row_factory=dict_row,connect_timeout=20) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(ADJUSTED_EVALUATION_SQL,(start,end))
                result=evaluate_adjusted(cur.fetchall(),holdout_start=holdout_start.isoformat(),
                                         round_trip_cost_bps=cost_bps)
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--start",type=date.fromisoformat,required=True)
    p.add_argument("--end",type=date.fromisoformat,required=True)
    p.add_argument("--holdout-start",type=date.fromisoformat,required=True)
    p.add_argument("--round-trip-cost-bps",type=int,default=30)
    p.add_argument("--output",type=Path)
    args=p.parse_args()
    result=run(os.getenv("DATABASE_URL",""),start=args.start,end=args.end,
               holdout_start=args.holdout_start,cost_bps=args.round_trip_cost_bps)
    output=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(output,encoding="utf-8")
    else:
        print(output)


if __name__=="__main__":
    main()
