"""Read-only real Neon source -> RAW-only exploratory AI input and purged backtest.

Different feature schema from frozen production Ridge. Never writes data,
never trains or replaces production weights, never claims return prediction.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from src.raw_factor_feature_bridge import MAX_BARS
from src.raw_factor_walkforward import (
    MAX_SIGNAL_DAYS,frozen_unadjusted_dataset,purged_ridge_prototype
)

# Six currently registered TPEx securities selected from an independent
# read-only raw-history audit, NOT historical listing-survival universe proof.
PROTOTYPE_STOCKS=("1742","1777","1781","1784","1785","1788")

PRICE_SQL="""SELECT market,stock_id,trade_date,open,high,low,close,volume,
turnover,price_change,transactions,source
FROM (
 SELECT market,stock_id,trade_date,open,high,low,close,volume,
 turnover,price_change,transactions,source
 FROM public.daily_prices
 WHERE market='tpex' AND stock_id=%s AND trade_date<=%s
 ORDER BY trade_date DESC LIMIT %s
) p ORDER BY trade_date"""
SIGNALS_SQL="""SELECT trade_date FROM public.daily_prices
WHERE market='tpex' AND stock_id=%s AND trade_date<=%s
 AND close>0 AND volume>=0 ORDER BY trade_date DESC LIMIT %s"""
MASTER_SQL="""SELECT COUNT(*)::int registered
FROM public.stock_master WHERE market='tpex'
AND stock_id=ANY(%s)"""

def execute(url,*,label_cutoff,test_start,max_signals=50,output_dir=None):
    if (not url or type(label_cutoff) is not date or type(test_start) is not date
        or test_start>=label_cutoff
        or type(max_signals) is not int or not 5<=max_signals<=MAX_SIGNAL_DAYS):
        raise ValueError("Protected source and bounded chronological research dates required")
    with psycopg.connect(url,connect_timeout=20,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='50000ms'")
        count=conn.execute(MASTER_SQL,(list(PROTOTYPE_STOCKS),)).fetchone()
        if count is None or count["registered"]!=len(PROTOTYPE_STOCKS):
            raise RuntimeError("Unexpected current TPEx source cohort; fail closed")
        series={}
        for sid in PROTOTYPE_STOCKS:
            series[sid]=[dict(x) for x in conn.execute(
                PRICE_SQL,(sid,label_cutoff,MAX_BARS)).fetchall()]
        signals=[r["trade_date"] for r in conn.execute(
            SIGNALS_SQL,(PROTOTYPE_STOCKS[0],label_cutoff,max_signals)).fetchall()]
    if len(signals)!=max_signals:
        raise RuntimeError("Insufficient actual saved TPEx sessions for bounded research")
    dataset=frozen_unadjusted_dataset(
        series,signal_dates=signals,label_cutoff=label_cutoff)
    if dataset["accepted_whole_cohort_days"]<5:
        raise RuntimeError("No credible complete frozen cohort for even exploratory research")
    evaluation=purged_ridge_prototype(dataset,test_start=test_start)
    report={
        "schema_version":1,
        "scope":"TPEX_RAW_ONLY_IN_MEMORY_MODEL_INPUT_AND_UNADJUSTED_PROTOTYPE",
        "feature_version":dataset["feature_version"],
        "included_stocks":len(PROTOTYPE_STOCKS),
        "original_source_rows_inspected":dataset["source_row_count"],
        "requested_actual_signal_dates":dataset["requested_signal_days"],
        "accepted_full_cohort_dates":dataset["accepted_whole_cohort_days"],
        "excluded_whole_dates_by_reason":dataset["excluded_whole_cohort_days"],
        "dataset_rows_sha256":dataset["rows_sha256"],
        "purged_exploratory_development_dates":evaluation["development_dates"],
        "holdout_independent_windows":len(evaluation["nonoverlap_test_windows"]),
        "prototype_status":evaluation["status"],
        "future_source_capture_vintage_independently_audited":False,
        "historical_issuer_listing_universe_audited":False,
        "raw_return_labels_adjusted_for_dividends":False,
        "production_tw_factor_ridge_1_unchanged":True,
        "no_new_persistent_factor_rows":True,
        "model_release_approved":False,"live_trading_approved":False,
        "line_trade_signals_approved":False,
        "database_read_only":True,"paid_service_required":False
    }
    if output_dir is not None:
        folder=Path(output_dir)
        folder.mkdir(parents=True,exist_ok=True)
        for name,value in (("research-dataset.json",dataset),
                           ("retrospective-ridge-prototype.json",evaluation),
                           ("research-source-gates.json",report)):
            (folder/name).write_text(
                json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n",
                encoding="utf-8")
    return report

def main():
    p=argparse.ArgumentParser(description="No-storage exploratory raw factor/label research integration")
    p.add_argument("--label-cutoff",type=date.fromisoformat,required=True)
    p.add_argument("--test-start",type=date.fromisoformat,required=True)
    p.add_argument("--max-signal-days",type=int,default=50)
    p.add_argument("--output-dir",type=Path,default=Path("raw-factor-research-proof"))
    a=p.parse_args()
    result=execute(os.getenv("DATABASE_URL",""),label_cutoff=a.label_cutoff,
                   test_start=a.test_start,max_signals=a.max_signal_days,
                   output_dir=a.output_dir)
    print(json.dumps(result,ensure_ascii=False))

if __name__=="__main__":
    main()
