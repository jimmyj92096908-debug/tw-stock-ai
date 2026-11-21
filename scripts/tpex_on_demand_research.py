"""Reproduce existing adjusted-price, technical and SMC research in memory.

Read-only stock-scoped TPEx OHLCV and verified corporate actions, no permanent
derived rows. The latest *research* panel is NOT historical point-in-time
corporate action vintage proof and may not be backtested for alpha without a
separate verified publication-vintage feed.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
import os
import sys

import psycopg
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from adjusted_prices import adjust_bars
from build_adjusted_prices import normalize_source_units
from technical_indicators import compute_indicators
from smc_indicators import compute_smc

MAX_SINGLE_STOCK_DAYS=1600
MAX_RETURN_DAYS=20

PRICE_SQL="""SELECT market,stock_id,trade_date,open,high,low,close,volume,
 turnover,price_change,transactions,source
 FROM public.daily_prices
 WHERE market=%s AND stock_id=%s AND trade_date<=%s
 ORDER BY trade_date LIMIT %s"""
ACTION_SQL="""SELECT ex_date,action_type,price_factor,share_factor,cash_amount,stock_amount
 FROM public.corporate_actions
 WHERE market=%s AND stock_id=%s AND verified=TRUE AND ex_date<=%s
 ORDER BY ex_date"""
STOCK_SQL="""SELECT EXISTS (SELECT 1 FROM public.stock_master
 WHERE market='tpex' AND stock_id=%s) AS listed_in_current_master"""

def evaluate(raw,actions,*,stock_id,cutoff:date,limit=MAX_RETURN_DAYS):
    if (not isinstance(cutoff,date) or type(cutoff) is not date
        or not isinstance(stock_id,str) or not stock_id.isascii()
        or not stock_id.isdigit() or not 1<=len(stock_id)<=6
        or type(limit) is not int or not 1<=limit<=MAX_RETURN_DAYS):
        raise ValueError("Bounded real TPEx stock and actual as-of date required")
    if (not isinstance(raw,list) or not 1<=len(raw)<=MAX_SINGLE_STOCK_DAYS
        or not isinstance(actions,list) or len(actions)>100):
        raise ValueError("Unbounded raw OHLCV or verified action series")
    prev=None
    for row in raw:
        if (row["market"]!="tpex" or row["stock_id"]!=stock_id
            or type(row["trade_date"]) is not date
            or row["trade_date"]>cutoff
            or (prev is not None and row["trade_date"]<=prev)):
            raise ValueError("Invalid or future-dated stock OHLCV sequence")
        prev=row["trade_date"]
    for a in actions:
        if (type(a["ex_date"]) is not date or a["ex_date"]>cutoff):
            raise ValueError("Corporate action is after the requested cutoff")
    normalized=normalize_source_units(raw,"tpex")
    adjusted=adjust_bars(normalized,actions)
    technical=compute_indicators(adjusted)
    smc=compute_smc(adjusted)
    if not (len(adjusted)==len(technical)==len(smc)==len(raw)):
        raise RuntimeError("In-memory source-to-factor reconciliation failed")
    panel=[]
    for k in range(max(0,len(raw)-limit),len(raw)):
        d=adjusted[k]["trade_date"]
        if technical[k]["trade_date"]!=d or smc[k]["trade_date"]!=d:
            raise RuntimeError("Adjusted/technical/SMC source date mismatch")
        panel.append({"trade_date":d.isoformat(),
                      "adjusted_close":adjusted[k]["close"],
                      "price_adjustment_status":adjusted[k]["adjustment_status"],
                      "technical":{key:value for key,value in technical[k].items()
                                   if key not in ("market","stock_id","trade_date")},
                      "smc":{key:value for key,value in smc[k].items()
                             if key not in ("market","stock_id","trade_date")}})
    return {
      "schema_version":1,"market":"tpex","stock_id":stock_id,
      "requested_cutoff":cutoff.isoformat(),
      "first_raw_date":raw[0]["trade_date"].isoformat(),
      "latest_raw_date":raw[-1]["trade_date"].isoformat(),
      "source_rows":len(raw),"returned_rows":len(panel),
      "verified_actions_as_of_ex_date":len(actions),
      "panel":panel,"latest_indicators":panel[-1],
      "uses_same_existing_adjusted_technical_smc_calculators":True,
      "corporate_action_publication_vintage_proven":False,
      "historical_backtest_or_alpha_approved":False,
      "in_memory_research_only":True,
      "database_writes":False,"permanent_derived_rows_created":0,
      "LINE_messages_sent":False,"trading_approved":False
    }

def run(url,*,stock_id,cutoff:date,limit=MAX_RETURN_DAYS):
    if not url:
        raise ValueError("Protected existing Neon DATABASE_URL required")
    if (type(cutoff) is not date or type(limit) is not int
        or not 1<=limit<=MAX_RETURN_DAYS
        or not isinstance(stock_id,str) or not stock_id.isascii()
        or not stock_id.isdigit()):
        raise ValueError("Strict real market-date or count required")
    with psycopg.connect(url,connect_timeout=20,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='35000ms'")
        known=conn.execute(STOCK_SQL,(stock_id,)).fetchone()
        if not known or known["listed_in_current_master"] is not True:
            raise ValueError("Unknown stock in current official TPEx universe")
        raw=[dict(r) for r in conn.execute(
            PRICE_SQL,("tpex",stock_id,cutoff,MAX_SINGLE_STOCK_DAYS+1)).fetchall()]
        if not raw or len(raw)>MAX_SINGLE_STOCK_DAYS:
            raise ValueError("Requested official stock history exceeds bounded in-memory budget")
        actions=[dict(r) for r in conn.execute(
            ACTION_SQL,("tpex",stock_id,cutoff)).fetchall()]
        report=evaluate(raw,actions,stock_id=stock_id,cutoff=cutoff,limit=limit)
    return report

def main():
    import argparse,json
    p=argparse.ArgumentParser(description="Read-only original TPEx source -> in-memory adjusted+technical+SMC")
    p.add_argument("--stock-id",required=True)
    p.add_argument("--as-of",type=date.fromisoformat,required=True)
    p.add_argument("--limit",type=int,default=1)
    p.add_argument("--report",type=Path,default=Path("tpex-on-demand-research.json"))
    a=p.parse_args()
    result=run(os.getenv("DATABASE_URL",""),stock_id=a.stock_id,cutoff=a.as_of,limit=a.limit)
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(result,ensure_ascii=False,default=str,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"stock_id":a.stock_id,"price_dates_processed":result["source_rows"],
        "indicators_reproduced":True,"database_writes":False,
        "corporate_action_publication_vintage_proven":False},ensure_ascii=False))

if __name__=="__main__":
    main()
