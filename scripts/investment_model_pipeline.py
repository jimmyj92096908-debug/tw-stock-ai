"""One entrypoint for the completed, research-only Taiwan stock model.

offline: verify committed research evidence without touching Neon.
live-readonly: in one repeatable-read snapshot, query existing score data and
produce an as-of-safe stock + ranking report. No DB mutations or LINE API.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from trained_factor_model import LATEST_MODEL_SQL
from investment_model_bundle import STOCK_STATUS_SQL, assemble_research_bundle

DEFAULT_MODEL = ROOT / "models" / "tw-factor-ridge-1-research.json"
DEFAULT_EVALUATION = ROOT / "models" / "tw-factor-ridge-1-evaluation.json"


def load_artifacts(model_path=DEFAULT_MODEL, evaluation_path=DEFAULT_EVALUATION):
    model = json.loads(Path(model_path).read_text(encoding="utf-8"))
    evaluation = json.loads(Path(evaluation_path).read_text(encoding="utf-8"))
    if not isinstance(model, dict) or not isinstance(evaluation, dict):
        raise ValueError("Research evidence must be JSON objects")
    return model, evaluation


def query_same_snapshot(database_url, market, stock_id):
    """One isolated MVCC snapshot, SELECT only; never query account/LINE data."""
    if not database_url:
        raise ValueError("DATABASE_URL is required for explicit live read-only audit")
    with psycopg.connect(
        database_url, connect_timeout=15, row_factory=dict_row,
        options="-c default_transaction_read_only=on"
    ) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                cur.execute("SET LOCAL statement_timeout = '20000ms'")
                cur.execute(LATEST_MODEL_SQL)
                ranked_rows = cur.fetchall()
                cur.execute(STOCK_STATUS_SQL, (market, stock_id) * 8)
                stock_rows = cur.fetchall()
                if len(stock_rows) != 1:
                    raise ValueError("Unable to read unique stock status")
                return ranked_rows, stock_rows[0]


def make_bundle(*, live=False, database_url="", market="twse", stock_id="2330",
                limit=10, model_path=DEFAULT_MODEL, evaluation_path=DEFAULT_EVALUATION):
    if market not in ("twse", "tpex"):
        raise ValueError("market must be twse or tpex")
    if not stock_id.isascii() or not stock_id.isdigit() or not 4 <= len(stock_id) <= 6:
        raise ValueError("stock_id must be 4..6 ASCII digits")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer from 1 to 100")
    model, evaluation = load_artifacts(model_path, evaluation_path)
    if live:
        if os.environ.get("INVESTMENT_MODEL_READONLY") != "yes":
            raise ValueError("Live stock query requires INVESTMENT_MODEL_READONLY=yes")
        ranking_rows, stock = query_same_snapshot(database_url, market, stock_id)
    else:
        ranking_rows, stock = [], {}
    bundle = assemble_research_bundle(
        model, evaluation, ranking_rows, stock, market=market,
        stock_id=stock_id, limit=limit
    )
    bundle["data_mode"] = "existing_neon_snapshot_read_only" if live else "offline_committed_evidence_only"
    bundle["offline_stock_data_is_not_live"] = not live
    bundle["as_of_now"] = date.today().isoformat()
    # Human-readable reason remains explicit even when a genuine snapshot
    # has stale composite/technical rows for today's reference price.
    return bundle


def main():
    parser = argparse.ArgumentParser(
        description="Taiwan stock research model: validated evidence and read-only ranking"
    )
    parser.add_argument("--live-readonly", action="store_true")
    parser.add_argument("--market", choices=("twse", "tpex"), default="twse")
    parser.add_argument("--stock-id", default="2330")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--model-in", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--evaluation-in", type=Path, default=DEFAULT_EVALUATION)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    bundle = make_bundle(
        live=args.live_readonly, database_url=os.getenv("DATABASE_URL", ""),
        market=args.market, stock_id=args.stock_id, limit=args.limit,
        model_path=args.model_in, evaluation_path=args.evaluation_in
    )
    output = json.dumps(bundle, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
        print(json.dumps({
            "output_file": str(args.output),
            "research_status": bundle["overall_status"],
            "abstain_from_trading": True,
            "data_mode": bundle["data_mode"],
        }, ensure_ascii=False))
    else:
        print(output)


if __name__ == "__main__":
    main()
