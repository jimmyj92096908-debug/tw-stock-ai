"""First-observed, bounded official quarterly general-industry income source.

Only append immutable issuer-quarter versions for known stock_master tickers.
No historical issuer publication date inference; EPS is cumulative YTD.
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
sys.path.insert(0,str(ROOT))
from src.official_quarterly_income_archive import SOURCES,MAX_ROWS,parse_snapshot

MAX_SOURCE_BYTES=8_000_000
MAX_DATABASE_BYTES=800_000_000
SIZE_SQL="SELECT pg_database_size(current_database())::bigint AS bytes"
COUNT_SQL="SELECT COUNT(*)::bigint AS n FROM public.official_quarterly_income_observations"

INSERT_SQL="""
INSERT INTO public.official_quarterly_income_observations
(market,stock_id,fiscal_year,fiscal_quarter,period_end,official_table_date,
 revenue_ytd_thousands_ntd,operating_income_ytd_thousands_ntd,
 net_income_ytd_thousands_ntd,basic_eps_ytd_ntd,eps_outlier_suppressed,
 first_observed_at,source_url,payload_sha256)
SELECT %(market)s::text,%(stock_id)s::varchar(6),
 %(fiscal_year)s::integer,%(fiscal_quarter)s::smallint,
 %(period_end)s::date,%(official_table_date)s::date,
 %(revenue_ytd_thousands_ntd)s::numeric(22,3),
 %(operating_income_ytd_thousands_ntd)s::numeric(22,3),
 %(net_income_ytd_thousands_ntd)s::numeric(22,3),
 %(basic_eps_ytd_ntd)s::numeric(16,6),
 %(eps_outlier_suppressed)s::boolean,
 %(first_observed_at)s::timestamptz,%(source_url)s::text,
 %(payload_sha256)s::char(64)
WHERE EXISTS(
 SELECT 1 FROM public.stock_master sm
 WHERE sm.market=%(market)s::text
 AND sm.stock_id=%(stock_id)s::varchar(6)
)
ON CONFLICT (market,stock_id,period_end,payload_sha256) DO NOTHING
"""


def fetch(market,*,session=None,observed_at=None):
    if market not in SOURCES:
        raise ValueError("Official quarterly market allowlist required")
    client=session or requests
    response=client.get(
        SOURCES[market],
        headers={"Accept":"application/json",
                 "User-Agent":"tw-stock-ai-research-quarterly-archive/1.0"},
        timeout=(10,30),allow_redirects=False)
    original=urlparse(SOURCES[market])
    result=urlparse(response.url)
    if response.status_code!=200 or result.scheme!="https" or        result.hostname!=original.hostname:
        raise RuntimeError("Untrusted official quarterly response or redirect")
    if len(response.content)>MAX_SOURCE_BYTES:
        raise RuntimeError("Official quarterly response over 8MB hard limit")
    try:
        rows=response.json()
    except ValueError as exc:
        raise RuntimeError("Official quarterly response not JSON") from exc
    timestamp=observed_at if observed_at is not None else datetime.now(ZoneInfo("Asia/Taipei"))
    return parse_snapshot(market,rows,observed_at=timestamp)


def _size(cur):
    cur.execute(SIZE_SQL)
    n=cur.fetchone()["bytes"]
    if type(n) is not int or not 0<n<MAX_DATABASE_BYTES:
        raise RuntimeError("Neon Free 800 MB hard-stop for official quarter archive")
    return n


def capture(url,*,apply=False,report_path=None,session=None,observed_at=None):
    if apply and os.environ.get("STOCK_QUARTERLY_SOURCE_ARCHIVE_WRITE")!="yes":
        raise PermissionError("Owner-approved quarterly archive opt-in gate required")
    if apply and observed_at is not None:
        raise ValueError("Cannot backdate a live official quarterly capture")
    # Validate BOTH official sources before any PostgreSQL changes.
    rows={
        m:fetch(m,session=session,observed_at=observed_at)
        for m in SOURCES
    }
    result={
        "schema_version":1,
        "research_source":"FIRST_OBSERVED_OFFICIAL_GENERAL_INDUSTRY_QUARTERLY_INCOME",
        "validated_source_rows":{m:len(v) for m,v in rows.items()},
        "inserted":0,"persisted":False,
        "first_observed_after_http":observed_at is None,
        "issuer_specific_published_at_unknown":True,
        "quarterly_eps_is_ytd_not_single_quarter":True,
        "cannot_retroactively_infer_old_signal_data":True,
        "financial_statement_full_market_coverage_proven":False,
        "model_weights_modified":False,
        "paid_service_required":False,
        "line_messages_sent":False,"live_trading_enabled":False,
    }
    if apply:
        if not url:
            raise ValueError("Protected existing Neon URL required")
        with psycopg.connect(url,autocommit=True,connect_timeout=15,row_factory=dict_row) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout = '30000ms'")
                    before=_size(cur)
                    cur.execute((ROOT/"sql/official_quarterly_income_observation_schema.sql").read_text(encoding="utf-8"))
                    cur.execute(COUNT_SQL)
                    old=cur.fetchone()["n"]
                    for market in SOURCES:
                        cur.executemany(INSERT_SQL,rows[market])
                    cur.execute(COUNT_SQL)
                    after=cur.fetchone()["n"]
                    if after<old or after-old>sum(len(v) for v in rows.values()):
                        raise RuntimeError("Actual official quarterly insert delta invalid")
                    end_bytes=_size(cur)
                    result.update({
                        "inserted":after-old,"persisted":True,
                        "database_before_bytes":before,
                        "database_after_bytes":end_bytes,
                    })
    if report_path:
        target=Path(report_path)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return result


def main():
    ap=argparse.ArgumentParser(description="Official first-observed quarterly income research-only")
    ap.add_argument("--apply",action="store_true")
    ap.add_argument("--report",type=Path,
                    default=Path("quarterly-income-first-seen-evidence.json"))
    args=ap.parse_args()
    report=capture(os.environ.get("DATABASE_URL",""),apply=args.apply,
                   report_path=args.report)
    print(json.dumps(report,ensure_ascii=False))


if __name__=="__main__":
    main()
