"""Bounded five-issuer direct TWSE cache expansion, owner-local only."""
import argparse
from hashlib import sha256
import json
from scripts import owner_twse_direct_monthly_source_canary as c
from scripts import owner_twse_tpex_quarterly_panel_merge_offline as m
from scripts import owner_quarterly_chip_vintage_coverage_readonly as chip

SALT="twse-monthly-5-pilot-20261125-v1"

def select(groups):
    latest=set(groups["twse",m.DATES[-1]])
    if not set(c.STOCKS)<=latest:
        raise ValueError("Original canary stocks not in frozen roster")
    common=set.intersection(*(set(groups["twse",d]) for d in m.DATES))
    pool=common-set(c.STOCKS)
    if len(pool)<3:
        raise ValueError("Insufficient anchor-complete candidate stocks")
    additional=sorted(pool,key=lambda sid:sha256((SALT+":"+sid).encode()).hexdigest())[:3]
    result=tuple(sorted((*c.STOCKS,*additional)))
    if any(not m.CODE.fullmatch(sid) or sid=="1589" for sid in result):
        raise ValueError("Invalid or excluded stock")
    return result

def queue_for(stocks,year,quarter):
    if (type(stocks) is not tuple or len(stocks)!=5 or len(set(stocks))!=5
        or not set(c.STOCKS)<=set(stocks) or type(year) is not int or not 2023<=year<=2026
        or type(quarter) is not int or not 1<=quarter<=4):
        raise ValueError("Fixed five-stock quarterly batch required")
    months=[f"{year}-{i:02d}" for i in range(3*quarter-2,3*quarter+1)
            if f"{year}-{i:02d}"<="2026-11"]
    return tuple((sid,month) for sid in stocks for month in months)

def run(payload,directory,year,quarter,*,get,sleeper=c.time.sleep):
    stocks=select(chip.verify_input(payload))
    q=queue_for(stocks,year,quarter)
    result=c.capture(directory,get=get,sleeper=sleeper,queue=q)
    result.update(scope="OWNER_TWSE_DIRECT_LOCAL_FIVE_STOCK_QUARTER_CAPTURE",
        sample_stock_count=5,year=year,quarter=quarter,
        frozen_sample_sha256=m.fingerprint(list(stocks)),
        selection_rule=SALT,
        source_rows_after_research_cutoff_may_be_cached=True,
        fresh_current_listing_not_independently_verified=True,
        independent_historical_universe_verified=False)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--panel",required=True);p.add_argument("--cache-dir",required=True)
    p.add_argument("--year",required=True,type=int);p.add_argument("--quarter",required=True,type=int)
    a=p.parse_args()
    try:
        payload,_=m.read_panel(m.private_path(a.panel,existing=True))
        import requests
        with requests.Session() as session:
            result=run(payload,a.cache_dir,a.year,a.quarter,get=session.get)
        print(json.dumps(result,allow_nan=False))
    except Exception:
        raise SystemExit("FAILED safely; private cache preserved; no Neon or LINE actions") from None

if __name__=="__main__":
    main()
