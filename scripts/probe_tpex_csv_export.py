"""Probe TPEx's current individual-stock page export formats (read-only)."""
from __future__ import annotations
import json, re
from datetime import date
from pathlib import Path
import requests

BASE = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
TARGETS = [("1259", "2026-10-05"), ("1264", "2025-09-08")]
OUT = Path("artifacts/tpex-csv-export-probe")

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update({"User-Agent":"Mozilla/5.0", "Referer":"https://www.tpex.org.tw/zh-tw/mainboard/trading/info/stock-pricing.html"})
    results=[]
    for code, iso in TARGETS:
        y,m,d=map(int,iso.split("-"))
        for response_mode in ("json","csv","html"):
            params={"response":response_mode,"date":f"{y}/{m:02d}/01","code":code}
            r=s.get(BASE,params=params,timeout=45)
            raw=r.content
            name=f"{code}-{iso}-{response_mode}.bin"
            (OUT/name).write_bytes(raw)
            text_body=r.text[:5000]
            item={"code":code,"date":iso,"mode":response_mode,"status":r.status_code,
                  "content_type":r.headers.get("Content-Type"),"final_url":r.url,
                  "bytes":len(raw),"file":name,"preview":text_body[:1200]}
            # JSON rows: preserve exact row and flag any OHLC numeric values
            try:
                j=r.json()
                item["json_keys"]=list(j) if isinstance(j,dict) else None
                tables=j.get("tables",[]) if isinstance(j,dict) else []
                rows=[row for t in tables for row in (t.get("data") or []) if row and str(row[0]).strip().startswith(f"{y-1911}/{m:02d}/{d:02d}")]
                item["target_rows"]=rows
            except Exception:
                item["json_parse"]="not-json"
            results.append(item)
            print(json.dumps(item,ensure_ascii=False))
    summary={"read_only":True,"database_accessed":False,"database_modified":False,
             "source_policy":"free official TPEx website only","results":results}
    (OUT/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
if __name__=="__main__": main()
