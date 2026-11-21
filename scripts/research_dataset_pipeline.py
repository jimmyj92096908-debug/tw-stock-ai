"""Generate bounded historical research JSON and explore factor IC.

The default source is an offline file. A manually opted-in Neon read requires
a separate protected *read-only* credential and RESEARCH_EXPORT_READONLY=yes.
No production write, LINE or network path is reachable in offline mode.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.research_dataset import build_research_dataset
from src.research_factor_diagnostics import factor_diagnostics

DB_READ_LIMIT = 40000
MAX_NEON_CALENDAR_DAYS = 120


def read_existing_neon_scores(database_url, *, start, end, max_rows=DB_READ_LIMIT):
    """Explicit, bounded, read-only historical export, never called by CI."""
    if os.environ.get("RESEARCH_EXPORT_READONLY") != "yes":
        raise PermissionError("Explicit RESEARCH_EXPORT_READONLY=yes required")
    if not database_url:
        raise ValueError("Protected PostgreSQL read-only DATABASE_URL required")
    if not isinstance(start,date) or not isinstance(end,date) or not (
            start <= end and (end-start).days <= MAX_NEON_CALENDAR_DAYS):
        raise ValueError("Neon research date window must be <=120 days")
    if type(max_rows) is not int or not 1 <= max_rows <= DB_READ_LIMIT:
        raise ValueError("Invalid bounded research row count")
    # Import lazily: no psycopg nor Neon connection needed for offline work.
    import psycopg
    from psycopg.rows import dict_row
    from src.trained_factor_model import TRAINING_SQL
    with psycopg.connect(
        database_url, connect_timeout=10,
        row_factory=dict_row, options="-c default_transaction_read_only=on"
    ) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                cur.execute("SET LOCAL statement_timeout = '20000ms'")
                cur.execute(TRAINING_SQL, (start,end))
                rows = cur.fetchmany(max_rows+1)
                if len(rows) > max_rows:
                    raise ValueError("Historical export exceeded read-only row cap")
                return rows


def prepare(*, rows, start, end, label_cutoff, source_mode):
    return build_research_dataset(
        rows, start=start, end=end, label_cutoff=label_cutoff,
        source_mode=source_mode)


def _write(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,indent=2,
                               ensure_ascii=False,allow_nan=False)+"\n",
                    encoding="utf-8")


def main():
    p=argparse.ArgumentParser(description="Research-only bounded as-of dataset pipeline")
    sub=p.add_subparsers(dest="command",required=True)
    b=sub.add_parser("prepare",help="Build a verified-shape historical JSON dataset")
    inputs=b.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--source-json",type=Path,help="Offline historical rows JSON")
    inputs.add_argument("--read-neon",action="store_true",
                        help="Opt-in read-only bounded query; may use free compute quota")
    b.add_argument("--start",type=date.fromisoformat,required=True)
    b.add_argument("--end",type=date.fromisoformat,required=True)
    b.add_argument("--label-cutoff",type=date.fromisoformat,required=True)
    b.add_argument("--output",type=Path,required=True)
    a=sub.add_parser("factors",help="Retrospective exploratory factor diagnostics")
    a.add_argument("--dataset",type=Path,required=True)
    a.add_argument("--exploration-end",type=date.fromisoformat,required=True)
    a.add_argument("--min-pairs",type=int,default=10)
    a.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    if args.command=="prepare":
        if args.read_neon:
            rows=read_existing_neon_scores(os.getenv("DATABASE_URL",""),
                                           start=args.start,end=args.end)
            source_mode="neon_existing_scores_readonly_no_independent_vintage_proof"
        else:
            rows=json.loads(args.source_json.read_text(encoding="utf-8"))
            source_mode="offline_user_supplied_unverified"
        report=prepare(rows=rows,start=args.start,end=args.end,
                       label_cutoff=args.label_cutoff,source_mode=source_mode)
        summary={"included_rows":report["manifest"]["included_rows"],
                 "included_dates":report["manifest"]["included_dates"],
                 "source_mode":source_mode}
    else:
        report=factor_diagnostics(
            json.loads(args.dataset.read_text(encoding="utf-8")),
            exploration_end=args.exploration_end,min_pairs=args.min_pairs)
        summary={"nonoverlapping_dates":report["nonoverlapping_evaluated_dates"],
                 "holdout_approved":False}
    _write(args.output,report)
    print(json.dumps({"output_file":str(args.output),**summary,
                      "orders_enabled":False},ensure_ascii=False))


if __name__=="__main__":
    main()
