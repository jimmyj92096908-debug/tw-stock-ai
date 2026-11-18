"""Fetch official TWSE TAIEX monthly history and persist daily index closes."""
from __future__ import annotations
import os, time, requests, psycopg
from datetime import date
try:
    from tdcc_data import normalize_database_url
except ModuleNotFoundError:
    from src.tdcc_data import normalize_database_url

URL="https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST"
HEADERS={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/plain,*/*"}
def num(v):
    s=str(v or "").replace(",","").strip()
    return float(s) if s and s not in ("--","-") else None
def parse_month(payload):
    if not isinstance(payload,dict) or payload.get("stat") not in ("OK","ok"):
        raise ValueError("TWSE TAIEX response status is not OK")
    fields=payload.get("fields") or []
    data=payload.get("data") or []
    idx={str(k).strip():i for i,k in enumerate(fields)}
    required=("日期","收盤指數")
    if any(k not in idx for k in required):
        raise ValueError(f"Unexpected TWSE TAIEX fields: {fields}")
    out=[]
    for row in data:
        raw=str(row[idx["日期"]]).strip()
        parts=raw.replace("-","/").split("/")
        if len(parts)!=3: raise ValueError(f"Invalid ROC date: {raw}")
        d=date(int(parts[0])+1911,int(parts[1]),int(parts[2]))
        close=num(row[idx["收盤指數"]])
        if close is not None: out.append((d,close))
    return out
def fetch_month(session,year,month):
    params={"date":f"{year}{month:02d}01","response":"json"}
    r=session.get(URL,params=params,headers=HEADERS,timeout=30)
    r.raise_for_status()
    return parse_month(r.json())
def main():
    start=int(os.getenv("INDEX_START_YEAR","2021"))
    end=int(os.getenv("INDEX_END_YEAR","2026"))
    if start>end: raise ValueError("INDEX_START_YEAR must be <= INDEX_END_YEAR")
    all_rows=[]
    with requests.Session() as session:
        for y in range(start,end+1):
            for m in range(1,13):
                if (y,m)>(date.today().year,date.today().month): continue
                try:
                    rows=fetch_month(session,y,m)
                    all_rows.extend(rows)
                    print(f"TAIEX {y}-{m:02d}: {len(rows)} rows")
                except Exception as e:
                    # Missing holiday/maintenance month should not be silently accepted.
                    raise RuntimeError(f"Failed TAIEX month {y}-{m:02d}: {e}") from e
                time.sleep(0.7)
    dedup={d:(d,c) for d,c in all_rows}
    rows=sorted(dedup.values())
    if len(rows)<500: raise RuntimeError(f"TAIEX history too short: {len(rows)}")
    with psycopg.connect(normalize_database_url(os.environ["DATABASE_URL"])) as conn:
        with conn.cursor() as cur:
            cur.executemany("""INSERT INTO market_index_prices(index_code,trade_date,close,source)
                VALUES('TAIEX',%s,%s,'TWSE MI_5MINS_HIST')
                ON CONFLICT(index_code,trade_date) DO UPDATE SET close=EXCLUDED.close,source=EXCLUDED.source""",
                [(d,c) for d,c in rows])
    print(f"TAIEX rows upserted: {len(rows)}; {rows[0][0]} to {rows[-1][0]}")
if __name__=="__main__": main()
