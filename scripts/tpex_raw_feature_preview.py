"""Read-only Neon source -> bounded in-memory causal raw research feature vectors.

No adjusted-price/technical/SMC permanent writes, no AI weights updated.
This produces a separate exploratory feature *schema*, not an unverified
conversion into historical composite scores or a model release.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from src.raw_factor_feature_bridge import (
    build_research_features,MAX_BARS,MAX_SIGNALS
)

MASTER_SQL="""SELECT EXISTS(
 SELECT 1 FROM public.stock_master WHERE market='tpex' AND stock_id=%s
) AS in_current_master"""
LAST_SOURCE_SQL="""SELECT market,stock_id,trade_date,open,high,low,close,volume,
turnover,price_change,transactions,source
FROM (
 SELECT market,stock_id,trade_date,open,high,low,close,volume,
 turnover,price_change,transactions,source
 FROM public.daily_prices WHERE market='tpex' AND stock_id=%s
 AND trade_date<=%s ORDER BY trade_date DESC LIMIT %s
) as recent_original ORDER BY trade_date"""
SIGNAL_SQL="""SELECT trade_date FROM public.daily_prices
WHERE market='tpex' AND stock_id=%s AND trade_date<=%s
AND close>0 AND volume>=0 ORDER BY trade_date DESC LIMIT %s"""

def preview(url,*,stock_id,cutoff,signals=3,report_path=None):
    if (not url or not isinstance(stock_id,str)
        or not stock_id.isascii() or not stock_id.isdigit()
        or len(stock_id) not in (4,5,6)
        or type(cutoff) is not date
        or type(signals) is not int or not 1<=signals<=MAX_SIGNALS):
        raise ValueError("Protected DB URL, stock, cutoff and signal bound required")
    with psycopg.connect(url,connect_timeout=20,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='35000ms'")
        known=conn.execute(MASTER_SQL,(stock_id,)).fetchone()
        if not known or known["in_current_master"] is not True:
            raise ValueError("Unverified current TPEx stock_master identifier")
        raw=[dict(x) for x in conn.execute(
            LAST_SOURCE_SQL,(stock_id,cutoff,MAX_BARS)).fetchall()]
        actual=[r["trade_date"] for r in conn.execute(
            SIGNAL_SQL,(stock_id,cutoff,signals)).fetchall()]
        if len(actual)!=signals:
            raise ValueError("Missing real official signal sessions")
    result=build_research_features(raw,stock_id=stock_id,
                                    cutoff=cutoff,signal_dates=actual)
    if result["included_signals"]!=signals:
        raise RuntimeError("No source-backed full warmup for requested signal features")
    if report_path is not None:
        file=Path(report_path)
        file.parent.mkdir(parents=True,exist_ok=True)
        file.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",
                        encoding="utf-8")
    return result

def main():
    p=argparse.ArgumentParser(description="Bounded current TPEx RAW source -> AI research feature schema only")
    p.add_argument("--stock-id",required=True)
    p.add_argument("--as-of",required=True,type=date.fromisoformat)
    p.add_argument("--signals",type=int,default=3)
    p.add_argument("--report",type=Path,default=Path("tpex-raw-feature-research.json"))
    a=p.parse_args()
    r=preview(os.getenv("DATABASE_URL",""),stock_id=a.stock_id,
              cutoff=a.as_of,signals=a.signals,report_path=a.report)
    print(json.dumps({"feature_version":r["feature_version"],
        "signal_dates_reproduced":r["included_signals"],
        "raw_original_bars":r["source_rows"],
        "source_sha256":r["raw_source_fingerprint_sha256"],
        "research_use_only":True,"existing_ridge_weights_modified":False,
        "new_persistent_factor_rows":0,"live_trading_approved":False},
        ensure_ascii=False))

if __name__=="__main__":
    main()
