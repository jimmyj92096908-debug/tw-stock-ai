"""Finite public-runner TPEx historical factor repair wave (research only).

Composes the existing fully tested 20-stock x 5-round (<=100 stocks)
source-validated worker at most five times. Every run independently checks
official source quality, original legacy unit conversions, the 800MB Neon
safety ceiling, actual FULL historical research coverage gain and cohort
stability. Never alters daily_prices, LINE, user billing, or trading.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.tpex_stale_factor_refresh import release_ready,release_snapshot

MAX_BATCHES=5
INNER_STOCK_CAP=100
INNER_ROUNDS=5
CHILD_TIMEOUT_SECONDS=2400

def validate(before,after,stocks):
    required=("tpex_source_days","tpex_eligible","tpex_matched",
              "legacy_rows","bad_legacy_volume","bad_legacy_turnover",
              "tpex_historical_factors_current","database_bytes")
    if any(type(before.get(k)) is not int or type(after.get(k)) is not int
           for k in required):
        raise RuntimeError("Invalid TPEx source/factor verification snapshot")
    if not release_ready(before) or not release_ready(after):
        raise RuntimeError("Official TPEx research, source, unit or Free-capacity gate failed")
    for key in ("tpex_source_days","tpex_eligible","tpex_matched",
                "legacy_rows","bad_legacy_volume","bad_legacy_turnover"):
        if before[key]!=after[key]:
            raise RuntimeError("TPEx batch scope or official source changed mid-campaign")
    if not isinstance(stocks,list) or len(stocks)>INNER_STOCK_CAP:
        raise RuntimeError("Unbounded TPEx historical factor worker output")
    ids=set()
    for stock in stocks:
        if (not isinstance(stock,dict) or
            not isinstance(stock.get("stock_id"),str) or
            not stock["stock_id"] or stock["stock_id"] in ids or
            stock.get("status")!="verified"):
            raise RuntimeError("Unverified or repeated TPEx historical factor result")
        ids.add(stock["stock_id"])
    previous=before["tpex_historical_factors_current"]
    now=after["tpex_historical_factors_current"]
    if not 0<=previous<=now<=after["tpex_eligible"]:
        raise RuntimeError("TPEx full-history factor count regressed or is impossible")
    if now-previous!=len(stocks):
        raise RuntimeError("Newly verified TPEx historical stock count does not reconcile")
    return len(stocks)


def save(path,record):
    if path is None:
        return
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(record,indent=2,ensure_ascii=False)+"\n",
                   encoding="utf-8")
    tmp.replace(path)


def execute(url,*,apply=False,max_batches=MAX_BATCHES,report_path=None,
            reader=release_snapshot, runner=subprocess.run):
    if not url:
        raise ValueError("Protected existing DATABASE_URL required")
    if type(max_batches) is not int or not 0<=max_batches<=MAX_BATCHES:
        raise ValueError("Unsafe TPEx historical multi-batch count")
    if apply and (max_batches<1 or
        os.environ.get("STOCK_TPEX_FACTOR_CAMPAIGN_ENABLED")!="yes" or
        os.environ.get("STOCK_TPEX_STALE_FACTOR_WRITE_ENABLED")!="yes" or
        os.environ.get("STOCK_INDICATOR_CATCHUP_WRITE_ENABLED")!="yes" or
        os.environ.get("STOCK_TPEX_STALE_SCORE_WRITE_ENABLED")!="yes"):
        raise ValueError("Multi-batch apply requires all four independent write gates")

    initial=reader(url)
    initial_ready=release_ready(initial)
    record={
        "schema_version":1,
        "scope":"TPEX_DATED_SOURCE_VERIFIED_HISTORICAL_FACTOR_RESEARCH_ONLY",
        "created_utc":datetime.now(timezone.utc).isoformat(),
        "batch_limit":max_batches,
        "max_stocks_per_batch":INNER_STOCK_CAP,
        "initial":initial,"latest":initial,
        "source_ready":initial_ready,
        "rounds":[], "finished":False,
        "raw_prices_modified":False,"line_trade_signals_sent":False,
        "paid_upgrade_requested":False,"trading_enabled":False,
    }
    save(report_path,record)
    if not apply:
        return record
    if not initial_ready:
        raise RuntimeError("Official dated TPEx source/legacy units or free storage not ready")

    previous=initial
    for idx in range(max_batches):
        if previous["tpex_historical_factors_current"]==previous["tpex_eligible"]:
            record["finished"]=True
            break
        child_path=(Path(report_path).with_name(
            "tpex-factor-source-batch-%02d.json"%(idx+1))
            if report_path else Path("tpex-factor-source-batch-%02d.json"%(idx+1)))
        command=[
            sys.executable,str(ROOT/"scripts/tpex_stale_factor_refresh.py"),
            "--apply","--rounds",str(INNER_ROUNDS),
            "--report",str(child_path),
        ]
        try:
            runner(command,check=True,capture_output=True,text=True,
                   timeout=CHILD_TIMEOUT_SECONDS)
        except (subprocess.CalledProcessError,subprocess.TimeoutExpired) as e:
            raise RuntimeError(
                "Source-gated TPEx historical worker failed closed; review batch evidence"
            ) from e
        if not child_path.exists():
            raise RuntimeError("Missing actual bounded historical factor batch evidence")
        child=json.loads(child_path.read_text(encoding="utf-8"))
        if child.get("raw_prices_modified") is not False or child.get("trading_enabled") is not False:
            raise RuntimeError("Unsafe historical factor worker output")
        after=reader(url)
        n=validate(previous,after,child.get("stocks"))
        record["rounds"].append({
            "batch":idx+1,"newly_verified":n,
            "historical_complete_after":after["tpex_historical_factors_current"],
            "eligible":after["tpex_eligible"],
            "neon_storage_bytes":after["database_bytes"],
            "zero_source_unit_errors":True,
        })
        record["latest"]=after
        save(report_path,record)
        if n==0:
            if after["tpex_historical_factors_current"]!=after["tpex_eligible"]:
                raise RuntimeError("No progress despite outstanding TPEx historical factor gap")
            record["finished"]=True
            break
        previous=after
    else:
        record["finished"]=(
            previous["tpex_historical_factors_current"]==previous["tpex_eligible"]
        )
    save(report_path,record)
    return record


def main():
    parser=argparse.ArgumentParser(description="Finite gated TPEx historical-factor source campaign")
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--max-batches",type=int,default=MAX_BATCHES)
    parser.add_argument("--report",type=Path,default=Path("tpex-factor-campaign-evidence.json"))
    opts=parser.parse_args()
    data=execute(os.environ.get("DATABASE_URL",""),apply=opts.apply,
                 max_batches=opts.max_batches,report_path=opts.report)
    print(json.dumps({
        "scope":data["scope"],
        "verified_batch_count":len(data["rounds"]),
        "new_historical_stocks":sum(x["newly_verified"] for x in data["rounds"]),
        "full_historical_stock_coverage":data["latest"]["tpex_historical_factors_current"],
        "eligible":data["latest"]["tpex_eligible"],
        "finished":data["finished"],
        "paid_upgrade_requested":False,"orders_enabled":False,
    },ensure_ascii=False))


if __name__=="__main__":
    main()
