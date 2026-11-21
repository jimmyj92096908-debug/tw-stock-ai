"""Fixed-stock TPEx historical monthly API read-only provenance probe.

No table mutations. Report only counts and date spans of official and stored
OHLC observations for the disputed old month vs latest month.
"""
from __future__ import annotations
import argparse
from datetime import date
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import time

import psycopg
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
import tpex_market_data
from scripts.tpex_official_history_insert_only import validate_official_month

STOCKS=("4183","6212")
MONTHS=(date(2026,7,1),date(2026,11,1))
MAX_CALLS=4
SAVED_SQL="""SELECT trade_date,close FROM public.daily_prices
WHERE market='tpex' AND stock_id=%s
 AND trade_date>=%s AND trade_date<%s AND close>0 AND volume>=0"""

def compare_month(stock_id,month,source_rows,saved_rows):
    approved=validate_official_month(stock_id,month,source_rows,today=date(2026,11,21))
    official={date.fromisoformat(r["trade_date"]):Decimal(str(r["close"])) for r in approved}
    saved={r["trade_date"]:Decimal(str(r["close"])) for r in saved_rows}
    overlap=set(official)&set(saved)
    matches=sum(official[d]==saved[d] for d in overlap)
    return {"stock_id":stock_id,"month":month.strftime("%Y-%m"),
            "official_rows":len(official),"stored_rows":len(saved),
            "same_date_overlap":len(overlap),"identical_closes":matches,
            "different_closes":len(overlap)-matches,
            "official_first":min(official).isoformat() if official else None,
            "official_last":max(official).isoformat() if official else None,
            "anchor_verified":len(overlap)>=2 and matches==len(overlap)}

def run(url,*,report_path=None,sleep_seconds=2.0):
    if not url:
        raise ValueError("Protected existing DATABASE_URL required")
    if not 0<=sleep_seconds<=5:
        raise ValueError("Invalid source API pause")
    result=[]
    with psycopg.connect(url,connect_timeout=15,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='20000ms'")
        for code in STOCKS:
            for month in MONTHS:
                # Four official calls maximum, two known month anchors each.
                rows=tpex_market_data.fetch_month(code,month.year,month.month)
                next_month=date(month.year+(month.month==12),month.month%12+1,1)
                saved=conn.execute(SAVED_SQL,(code,month,next_month)).fetchall()
                result.append(compare_month(code,month,rows,saved))
                if len(result)<MAX_CALLS and sleep_seconds:
                    time.sleep(sleep_seconds)
    report={"schema_version":1,"scope":"TPEX_FIXED_HISTORICAL_MONTH_SOURCE_READ_ONLY",
            "official_month_requests":len(result),"max_official_calls":MAX_CALLS,
            "database_read_only":True,"database_written":False,
            "stock_price_rows_modified":False,"paid_api_used":False,
            "line_messages_sent":False,"stock_months":result}
    if report_path is not None:
        dest=Path(report_path)
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report

def main():
    arg=argparse.ArgumentParser(description="Read-only TPEx July/November official anchor probe")
    arg.add_argument("--report",type=Path,default=Path("tpex-backward-source-probe.json"))
    opts=arg.parse_args()
    print(json.dumps(run(os.getenv("DATABASE_URL",""),report_path=opts.report),ensure_ascii=False))

if __name__=="__main__":
    main()
