"""Bounded source archive of currently observable exchange monthly revenue.

Only stored as first-seen observations; never assert first_observed_at is the
issuer's actual release timestamp. Source URLs are a fixed official allowlist.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
import requests

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from official_revenue_archive import SOURCES,MAX_ROWS,parse_snapshot

MAX_SOURCE_BYTES=6_000_000
MAX_DB_BYTES=800_000_000
STORAGE_GUARD="SELECT pg_database_size(current_database())::bigint AS bytes"
INSERT_SQL="""
INSERT INTO public.official_revenue_observations
(market,stock_id,period_end,reported_revenue_thousands_ntd,
 reported_yoy_pct,official_table_date,first_observed_at,source_url,payload_sha256)
SELECT %(market)s,%(stock_id)s,%(period_end)s,
       %(reported_revenue_thousands_ntd)s,
       %(reported_yoy_pct)s,%(official_table_date)s,
       %(first_observed_at)s,%(source_url)s,%(payload_sha256)s
WHERE EXISTS(SELECT 1 FROM public.stock_master sm
             WHERE sm.market=%(market)s AND sm.stock_id=%(stock_id)s)
ON CONFLICT (market,stock_id,period_end,payload_sha256) DO NOTHING
"""
COUNT_SQL="SELECT COUNT(*)::bigint AS n FROM public.official_revenue_observations"


def fetch_market(market,*,observed_at=None,session=None):
    if market not in SOURCES:
        raise ValueError("Unknown official source")
    session=session or requests
    res=session.get(
        SOURCES[market],headers={"Accept":"application/json",
                                 "User-Agent":"tw-stock-ai-research-archive/1.0"},
        timeout=(10,25),allow_redirects=False)
    if not (res.status_code==200 and
            urlparse(res.url).scheme=="https" and
            urlparse(res.url).hostname==urlparse(SOURCES[market]).hostname):
        raise RuntimeError("Official source HTTP/host validation failed")
    if len(res.content)>MAX_SOURCE_BYTES:
        raise RuntimeError("Official JSON exceeds free-tier response size cap")
    try:
        raw=res.json()
    except ValueError as e:
        raise RuntimeError("Official endpoint did not return JSON") from e
    # Never label a source value as observed before the response is received.
    captured=datetime.now(ZoneInfo('Asia/Taipei')) if observed_at is None else observed_at
    return parse_snapshot(market,raw,observed_at=captured)


def _size(conn):
    with conn.cursor() as cur:
        cur.execute(STORAGE_GUARD)
        n=cur.fetchone()["bytes"]
    if type(n) is not int or not 0<n<MAX_DB_BYTES:
        raise RuntimeError("Neon Free 800MB storage stop line")
    return n


def capture(url,*,apply=False,observed_at=None,report_path=None,session=None):
    if apply and os.getenv("STOCK_OFFICIAL_REVENUE_ARCHIVE_WRITE")!="yes":
        raise PermissionError("Explicit one-time official-source archive gate missing")
    # Keep first-observed time conservative: after the HTTP request returns,
    # never before it. Do not use source table dates as publication timestamps.
    if observed_at is not None and apply:
        raise ValueError("Live insert cannot supply a custom/backdated first-observed time")
    if observed_at is not None:
        timestamp=observed_at
        rows={market:fetch_market(market,observed_at=timestamp,session=session)
              for market in SOURCES}
    else:
        # fetch_market assigns capture time after the official HTTP response.
        rows={market:fetch_market(market,session=session) for market in SOURCES}
    count=sum(len(items) for items in rows.values())
    if count>MAX_ROWS*len(SOURCES):
        raise RuntimeError("Official source row count exceeds bounded monthly snapshot")
    result={
        "schema_version":1,
        "source":"EXCHANGE_OFFICIAL_LATEST_MONTHLY_REVENUE_SNAPSHOT",
        "rows_validated":{k:len(v) for k,v in rows.items()},
        "inserted":0,"persisted":False,
        "exact_release_timestamp_known":False,
        "historical_before_first_capture_not_inferred":True,
        "point_in_time_data_not_backdated":True,
        "source_credentials_or_api_keys_required":False,
        "new_paid_services":False,
        "model_trained_or_promoted":False,
        "line_messages_sent":False,"trading_enabled":False,
    }
    if apply:
        if not url:
            raise ValueError("Protected existing DATABASE_URL required")
        with psycopg.connect(url,connect_timeout=15,row_factory=dict_row) as conn:
            before=_size(conn)
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout='25000ms'")
                    cur.execute((ROOT/"sql/official_revenue_observation_schema.sql").read_text(encoding="utf-8"))
                    cur.execute(COUNT_SQL)
                    n0=cur.fetchone()["n"]
                    for market in SOURCES:
                        cur.executemany(INSERT_SQL,rows[market])
                    cur.execute(COUNT_SQL)
                    n1=cur.fetchone()["n"]
                    if n1<n0 or n1-n0>count:
                        raise RuntimeError("Impossible insert-only verified revenue archive delta")
                # A capture must never cause storage beyond the explicit Free guard.
                after=_size(conn)
                if after>=MAX_DB_BYTES:
                    raise RuntimeError("Official archived data violates Free storage ceiling")
                result["inserted"]=n1-n0
                result["persisted"]=True
                result["before_database_bytes"]=before
                result["after_database_bytes"]=after
    if report_path:
        path=Path(report_path)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result


def main():
    p=argparse.ArgumentParser(description="Record first-seen official monthly revenue, research-only")
    p.add_argument("--apply",action="store_true")
    p.add_argument("--report",type=Path,default=Path("official-revenue-archive-evidence.json"))
    a=p.parse_args()
    out=capture(os.getenv("DATABASE_URL",""),apply=a.apply,report_path=a.report)
    print(json.dumps(out,ensure_ascii=False))


if __name__=="__main__":
    main()
