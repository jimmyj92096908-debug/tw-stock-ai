"""Read-only release milestones for data provenance and prospective model evidence.

Reuses existing official-source acceptance predicates; no raw market changes,
new scheduler, new branch, LINE message, trading signal or payment. The output
never declares a trained model profitable because prospective cohorts exist.
"""
from __future__ import annotations

import argparse
from datetime import date,datetime,timezone
import json
import os
from pathlib import Path
import sys

import psycopg
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.twse_240_release_gate import snapshot,decide

FREEZE_SQL="""
SELECT COUNT(*)::bigint AS frozen_cohorts,
       COUNT(DISTINCT signal_date)::int AS frozen_signal_days,
       MIN(signal_date) AS first_signal,
       MAX(signal_date) AS latest_signal,
       COUNT(*) FILTER (WHERE frozen_at <= signal_date::timestamptz)::int
           AS implausible_frozen_timestamps
FROM public.research_forward_frozen_cohorts
WHERE model_version='tw-factor-ridge-1'
"""


def read_frozen_evidence(url):
    if not url:
        raise ValueError("Protected DATABASE_URL required")
    with psycopg.connect(url,connect_timeout=15,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout='30000ms'")
        result=dict(conn.execute(FREEZE_SQL).fetchone())
    for key in ("frozen_cohorts","frozen_signal_days",
                "implausible_frozen_timestamps"):
        if type(result.get(key)) is not int or result[key]<0:
            raise RuntimeError("Invalid committed frozen-cohort evidence")
    if (result["frozen_cohorts"]!=result["frozen_signal_days"] or
        result["implausible_frozen_timestamps"]!=0):
        raise RuntimeError("Frozen model snapshots contain conflicting research provenance")
    if bool(result["frozen_cohorts"]) != bool(result["latest_signal"]):
        raise RuntimeError("Missing or impossible last prospective signal date")
    return result


def report_from_evidence(state,frozen):
    """Never substitute a prospective roster for fully matured future returns."""
    if any(type(state.get(k)) is not int for k in (
        "tpex_source_days","twse_source_days","legacy_rows",
        "bad_legacy_volume","bad_legacy_turnover","tpex_eligible",
        "tpex_matched","twse_240_eligible","twse_full_indicators",
        "twse_complete_scores","database_bytes"
    )):
        raise ValueError("Unverified official source milestones")
    if (min(state.values())<0 or state["bad_legacy_volume"]>state["legacy_rows"]
        or state["bad_legacy_turnover"]>state["legacy_rows"]):
        raise ValueError("Contradictory legacy market-unit statistics")
    if not isinstance(frozen,dict) or type(frozen.get("frozen_cohorts")) is not int:
        raise ValueError("Missing immutable model roster evidence")
    if type(frozen.get("frozen_signal_days")) is not int:
        raise ValueError("Invalid prospective signal-day count")
    newest=frozen.get("latest_signal")
    if newest is not None and type(newest) is not date:
        raise ValueError("Frozen latest signal date must be a PostgreSQL DATE")
    return {
        "schema_version":1,
        "collected_at_utc":datetime.now(timezone.utc).isoformat(),
        "official_history":{
            "tpex_dated_verified_sessions":state["tpex_source_days"],
            "twse_dated_verified_sessions":state["twse_source_days"],
            "twse_240_day_source_gate":bool(decide("source",state)),
            "twse_240_day_research_gate":bool(decide("research",state)),
        },
        "legacy_tpex_units":{
            "raw_legacy_rows":state["legacy_rows"],
            "derived_volume_bad_or_missing":state["bad_legacy_volume"],
            "derived_turnover_bad_or_missing":state["bad_legacy_turnover"],
            "all_source_units_verified":bool(
                state["legacy_rows"]>0 and
                state["bad_legacy_volume"]==0 and
                state["bad_legacy_turnover"]==0
            ),
        },
        "current_research":{
            "tpex_60_session_eligible":state["tpex_eligible"],
            "tpex_latest_full_stack":state["tpex_matched"],
            "twse_240_session_eligible":state["twse_240_eligible"],
            "twse_full_240_session_indicators":state["twse_full_indicators"],
            "twse_latest_scores_on_full_240_factors":state["twse_complete_scores"],
        },
        "future_research":{
            "immutable_frozen_cohorts":frozen["frozen_cohorts"],
            "frozen_signal_days":frozen["frozen_signal_days"],
            "latest_signal_date":newest.isoformat() if newest else None,
            "future_holdout_statistically_validated":False,
            "all_forward_labels_matured":False,
            "independently_verified_positive_alpha":False,
        },
        "budget":{"neon_database_bytes":state["database_bytes"],
                  "conservative_stop_bytes":800_000_000,
                  "paid_upgrade_requested":False},
        "safety":{"read_only":True,"raw_price_updates":False,
                  "line_trade_signal_enabled":False,
                  "orders_enabled":False,"live_trading_approved":False},
    }


def execute(url,*,report_path=None):
    state=snapshot(url)
    frozen=read_frozen_evidence(url)
    report=report_from_evidence(state,frozen)
    if report_path is not None:
        target=Path(report_path)
        target.parent.mkdir(parents=True,exist_ok=True)
        tmp=target.with_suffix(target.suffix+".tmp")
        tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",
                       encoding="utf-8")
        tmp.replace(target)
    return report


def main():
    parser=argparse.ArgumentParser(description="Only read Neon official research milestones")
    parser.add_argument("--out",type=Path,default=Path("twstock-research-milestones.json"))
    args=parser.parse_args()
    out=execute(os.getenv("DATABASE_URL",""),report_path=args.out)
    print(json.dumps({
        "source_days":out["official_history"],
        "legacy_units":out["legacy_tpex_units"],
        "frozen_cohorts":out["future_research"]["immutable_frozen_cohorts"],
        "model_release_approved":False,
        "line_trade_signal_enabled":False,
        "database_writes":False,
    },ensure_ascii=False))


if __name__=="__main__":
    main()
