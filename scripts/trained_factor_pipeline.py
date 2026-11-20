"""Reproducible read-only training and ranking for tw-stock-ai factor model.

The sole dataset source is the existing official-market-backed Neon database.
No price fabrication, secret export, table mutation, LINE call, or order entry.
Use the restricted read-only PostgreSQL role, not a production writer secret.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from trained_factor_model import (
    TRAINING_SQL, LATEST_MODEL_SQL, research_rank, train_and_verify,
)


def read_only_rows(database_url, sql, params=()):
    if not database_url:
        raise ValueError("Set a read-only DATABASE_URL in protected environment")
    with psycopg.connect(database_url, connect_timeout=20, row_factory=dict_row) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                # PostgreSQL refuses INSERT/UPDATE/DELETE inside this transaction.
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(sql, params)
                return cur.fetchall()


def write_json(path, payload):
    """Save only aggregates and numeric weights, never database credentials."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def execute_train(database_url, *, start, holdout_start, end, model_out, report_out):
    if not (start < holdout_start < end) or (end - start).days > 366:
        raise ValueError("Invalid bounded training / holdout date split")
    rows = read_only_rows(database_url, TRAINING_SQL, (start, end))
    model, report = train_and_verify(rows, holdout_start=holdout_start)
    model["data_start"] = start.isoformat()
    model["data_end"] = end.isoformat()
    # This artifact is a reproducible trained model, NOT a release authorization.
    model["source"] = "verified-market-backed-Neon-readonly"
    write_json(model_out, model)
    write_json(report_out, report)
    return {
        "trained_development_days": model["development_dates"],
        "holdout_days": report["holdout"]["dates"],
        "model_file": str(model_out), "report_file": str(report_out),
        "holdout_research_gate_passed": report["holdout_research_gate_passed"],
        "live_trading_approved": False,
    }


def execute_rank(database_url, *, model_path, output, limit):
    model = json.loads(Path(model_path).read_text(encoding="utf-8"))
    rows = read_only_rows(database_url, LATEST_MODEL_SQL)
    result = research_rank(rows, model, limit=limit)
    result["artifact_development_sha256"] = model.get("development_sha256")
    result["holdout_verified_for_trading"] = False
    write_json(output, result)
    return {"output_file": str(output), "ranked": len(result["stocks"]),
            "abstain": result["abstain"]}


def main():
    parser = argparse.ArgumentParser(description="Read-only trained Taiwan factor research model")
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train")
    train.add_argument("--start", type=date.fromisoformat, required=True)
    train.add_argument("--holdout-start", type=date.fromisoformat, required=True)
    train.add_argument("--end", type=date.fromisoformat, required=True)
    train.add_argument("--model-out", type=Path, required=True)
    train.add_argument("--report-out", type=Path, required=True)
    rank = sub.add_parser("rank")
    rank.add_argument("--model-in", type=Path, required=True)
    rank.add_argument("--output", type=Path, required=True)
    rank.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    db_url = os.getenv("DATABASE_URL", "")
    if args.command == "train":
        summary = execute_train(db_url, start=args.start,
                                holdout_start=args.holdout_start, end=args.end,
                                model_out=args.model_out, report_out=args.report_out)
    else:
        summary = execute_rank(db_url, model_path=args.model_in,
                               output=args.output, limit=args.limit)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
