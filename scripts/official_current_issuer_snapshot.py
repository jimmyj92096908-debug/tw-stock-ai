"""Bounded OFFICIAL current-issuer listing evidence and immutable weekly archive.

The current official company basic-info feeds contain listing dates for
surviving issuers, but they do NOT reconstruct prior delisted/suspended,
transferred or reissued stocks at every historical signal. Do NOT use a
current-company listing date to claim a survivorship-free backtest universe.
"""
from __future__ import annotations

from datetime import date,datetime,timezone,timedelta
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlparse
import argparse,json,os,re

import psycopg
from psycopg.rows import dict_row

from src.stock_list import TWSE_URL,TPEX_URL,fetch_json,normalize_rows

MAX_ROWS_PER_MARKET=3000
MAX_REPORT_BYTES=1_000_000
STORAGE_STOP_BYTES=650_000_000
REQUIRED_SOURCE_HOSTS={"openapi.twse.com.tw","www.tpex.org.tw"}
LISTING_KEYS={
    "twse":("上市日期","上市年月日","ListingDate","SecuritiesListingDate"),
    "tpex":("上櫃日期","上櫃年月日","ListingDate","SecuritiesListingDate"),
}
MASTER_SQL="""SELECT market,stock_id FROM public.stock_master
WHERE market IN ('twse','tpex')"""
SIZE_SQL="SELECT pg_database_size(current_database())::bigint AS bytes"
READ_SQL="""SELECT payload_sha256,observed_at FROM public.official_issuer_weekly_snapshots
WHERE observed_week=%s"""
INSERT_SQL="""INSERT INTO public.official_issuer_weekly_snapshots
(observed_week,payload_sha256,snapshot)
VALUES (%s,%s,%s::jsonb)
ON CONFLICT(observed_week) DO NOTHING
RETURNING payload_sha256"""

def listing_date(value):
    if value is None or not str(value).strip() or str(value).strip() in ("--","-"):
        return None
    raw=str(value).strip()
    digits=re.fullmatch(r"(\d{7,8})",raw)
    if digits:
        token=digits.group(1)
        y=int(token[:-4]);mo=int(token[-4:-2]);d=int(token[-2:])
    else:
        text=re.sub("[年月]","/",raw).replace("日","").replace("-","/")
        m=re.fullmatch(r"(\d{2,4})/(\d{1,2})/(\d{1,2})",text)
        if not m:
            raise ValueError("Unknown official listing date format")
        y,mo,d=map(int,m.groups())
    if y<1911:y+=1911
    if y<1950 or y>date.today().year+1:
        raise ValueError("Official listing year outside credible range")
    return date(y,mo,d).isoformat()

def _value(row,keys):
    for name in keys:
        if row.get(name) is not None and str(row[name]).strip():
            return str(row[name]).strip()
    return None

def build_snapshot(twse_rows,tpex_rows,*,captured_at,master_pairs=None):
    if not isinstance(captured_at,datetime) or captured_at.tzinfo is None:
        raise ValueError("Actual timezone-aware first-captured time required")
    all_records=[]
    counts={}
    for market,source,raw in (
        ("twse",TWSE_URL,twse_rows),("tpex",TPEX_URL,tpex_rows)
    ):
        if urlparse(source).hostname not in REQUIRED_SOURCE_HOSTS:
            raise ValueError("Non-official market source")
        if not isinstance(raw,list) or not 600<=len(raw)<=MAX_ROWS_PER_MARKET:
            raise ValueError("Missing, incomplete or oversized official issuer response")
        normalized=normalize_rows(raw,"上市" if market=="twse" else "上櫃")
        if not 600<=len(normalized)<=MAX_ROWS_PER_MARKET:
            raise ValueError("Could not verify official listed-equity code universe")
        lookup={r.get("公司代號",r.get("SecuritiesCompanyCode",
                  r.get("證券代號",r.get("股票代號","")))):r for r in raw if isinstance(r,dict)}
        found=0
        for record in normalized:
            sid=record["stock_id"]
            if not re.fullmatch(r"\d{4}",sid):
                raise ValueError("Malformed issuer symbol")
            doc=lookup.get(sid)
            # Stock-list helper may support a new code alias; fail closed if
            # the original evidence row cannot be retrieved for date proof.
            if doc is None:
                raise ValueError("Official normalized stock missing original row")
            day=listing_date(_value(doc,LISTING_KEYS[market]))
            if day is not None:found+=1
            all_records.append({"market":market,"stock_id":sid,
                "name":record["stock_name"],"industry":record["industry"],
                "current_api_listing_date":day,"source":source})
        counts[market]={"current_official_company_rows":len(normalized),
                        "company_rows_with_official_listing_date":found,
                        "rows_missing_original_listing_date":len(normalized)-found}
    pairs=[(r["market"],r["stock_id"]) for r in all_records]
    if len(pairs)!=len(set(pairs)):
        raise ValueError("Duplicate official issuer or cross-feed mismatch")
    all_records.sort(key=lambda x:(x["market"],x["stock_id"]))
    roster=set(pairs)
    if master_pairs is not None:
        existing=set(master_pairs)
        if not existing:
            raise ValueError("Current stock_master source is missing")
        only_in_master=sorted(existing-roster)
        only_in_api=sorted(roster-existing)
    else:
        only_in_master=[];only_in_api=[]
    # A captured issuer API snapshot is NOT a historical delisted universe.
    snap={
        "schema_version":1,"scope":"OFFICIAL_CURRENT_ISSUER_SNAPSHOT_NOT_HISTORICAL_SURVIVORSHIP_PROOF",
        "captured_at_utc":captured_at.astimezone(timezone.utc).isoformat(),
        "sources":{"twse":TWSE_URL,"tpex":TPEX_URL},
        "market_counts":counts,
        "current_official_issuer_pairs":len(roster),
        "api_missing_today_master_count":len(only_in_master),
        "master_missing_current_api_count":len(only_in_api),
        "api_missing_today_master_sample":only_in_master[:12],
        "master_missing_current_api_sample":only_in_api[:12],
        "records":all_records,
        "original_issuer_listing_date_proven_only_for_current_issuer":True,
        "historical_delisted_issuer_population_complete":False,
        "historical_suspended_or_transferred_issuers_verified":False,
        "full_historic_point_in_time_investible_universe_approved":False,
        "current_stock_master_updated_at_is_not_original_listing_date":True,
        "cannot_backdate_capture_time":True,
        "LINE_or_trading_enabled":False,
        "paid_data_used":False,
    }
    packed=json.dumps(snap,sort_keys=True,ensure_ascii=False,
                      separators=(",",":"),allow_nan=False).encode()
    if len(packed)>MAX_REPORT_BYTES:
        raise ValueError("Current official issuer universe oversized")
    snap["payload_sha256"]=sha256(packed).hexdigest()
    return snap

def weekly_date(captured_at):
    local=captured_at.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Taipei")).date()
    return local-timedelta(days=local.weekday())

def freeze_weekly(url,snapshot,*,apply=False):
    if apply and os.environ.get("STOCK_OFFICIAL_ISSUER_EVIDENCE_WRITE")!="yes":
        raise PermissionError("Protected issuer-only insert gate must be enabled")
    if not url:
        raise ValueError("Existing Neon connection required")
    data=json.dumps(snapshot,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    if len(data.encode())>MAX_REPORT_BYTES+200:
        raise ValueError("Official issuer payload too large for Free storage")
    observed=datetime.fromisoformat(snapshot["captured_at_utc"])
    week=weekly_date(observed)
    with psycopg.connect(url,connect_timeout=15,row_factory=dict_row,
                         options=None if apply else "-c default_transaction_read_only=on") as conn:
        with conn.transaction():
            conn.execute("SET LOCAL statement_timeout='20000ms'")
            size=conn.execute(SIZE_SQL).fetchone()["bytes"]
            if type(size) is not int or size>=STORAGE_STOP_BYTES:
                raise RuntimeError("Fail closed at 650MB before small official evidence write")
            if not apply:
                return {"persisted":False,"observed_week":week.isoformat(),
                        "payload_sha256":snapshot["payload_sha256"],
                        "db_bytes":size,"database_writes":0}
            ddl=(Path(__file__).resolve().parents[1]/
                 "sql/official_issuer_weekly_snapshots.sql").read_text()
            conn.execute(ddl)
            conn.execute(INSERT_SQL,(week,snapshot["payload_sha256"],data))
            created=conn.fetchone() if False else None
            # psycopg connection.execute returns a cursor; use explicit result.
            prior=conn.execute(READ_SQL,(week,)).fetchone()
            if prior is None or prior["payload_sha256"].strip()!=snapshot["payload_sha256"]:
                raise RuntimeError("Existing weekly official source proof cannot be overwritten")
            if conn.execute(SIZE_SQL).fetchone()["bytes"]>=STORAGE_STOP_BYTES:
                raise RuntimeError("Would exceed free safety reserve")
    return {"persisted":True,"observed_week":week.isoformat(),
            "payload_sha256":snapshot["payload_sha256"],
            "new_or_same_preexisting":True,"database_writes":1}

def run(url,*,apply=False,report_path=None):
    # Download exact two authoritative endpoints; never fabricate historical
    # listings not present in the latest API response.
    twse=fetch_json(TWSE_URL)
    tpex=fetch_json(TPEX_URL)
    now=datetime.now(timezone.utc)
    with psycopg.connect(url,connect_timeout=15,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='20000ms'")
        pairs=[(r["market"],r["stock_id"]) for r in conn.execute(MASTER_SQL).fetchall()]
    snapshot=build_snapshot(twse,tpex,captured_at=now,master_pairs=pairs)
    result=freeze_weekly(url,snapshot,apply=apply)
    summary={k:v for k,v in snapshot.items() if k!="records"}
    summary["verified_writes"]=result
    if report_path:
        path=Path(report_path);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return summary

def main():
    ap=argparse.ArgumentParser(description="Current official issuer-list evidence, not past PIT delisted master")
    ap.add_argument("--apply",action="store_true")
    ap.add_argument("--report",type=Path,default=Path("current-official-issuer-evidence.json"))
    args=ap.parse_args()
    res=run(os.getenv("DATABASE_URL",""),apply=args.apply,report_path=args.report)
    print(json.dumps({k:res[k] for k in (
        "market_counts","payload_sha256",
        "historical_delisted_issuer_population_complete","verified_writes"
    )},ensure_ascii=False))

if __name__=="__main__":
    main()
