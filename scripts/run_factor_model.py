"""Generate today's available historical ranking; never write to Neon or LINE."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import psycopg
from psycopg.rows import dict_row

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / "src"))
from factor_model import LATEST_RANKING_SQL, ranking

def read_latest(database_url, limit=10):
    if not database_url:
        raise ValueError("DATABASE_URL required")
    with psycopg.connect(database_url,row_factory=dict_row,connect_timeout=20) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(LATEST_RANKING_SQL,(0.50,))
                return ranking(cur.fetchall(),limit=limit)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--limit",type=int,default=10)
    p.add_argument("--output",type=Path)
    args=p.parse_args()
    report=json.dumps(read_latest(os.getenv("DATABASE_URL",""),args.limit),
                      ensure_ascii=False,indent=2)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(report,encoding="utf-8")
    else:
        print(report)

if __name__=="__main__":
    main()
