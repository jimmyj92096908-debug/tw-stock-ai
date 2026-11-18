"""Import official TWSE/TPEx ex-right/ex-dividend records.

Only cash-only events are automatically verified. Stock-right and mixed events are
stored for review because the feed's headline reference price alone does not provide
a reliable share-conversion factor.
"""
from __future__ import annotations
import argparse, hashlib, json, logging, os, re, time
from datetime import date
from typing import Any
import requests
import psycopg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger(__name__)
TWSE_URL="https://www.twse.com.tw/rwd/zh/exRight/TWT49U"
TPEX_URL="https://www.tpex.org.tw/openapi/v1/tpex_exright_daily"
TARGETS={"twse":{"6213","4919","7827"},"tpex":{"8937"}}

def _norm(s: Any)->str:
 return re.sub(r"[\s\ufeff（）()％%]", "", str(s or "")).lower()

def _pick(row:dict, aliases:list[str])->Any:
 mapped={_norm(k):v for k,v in row.items()}
 for alias in aliases:
  key=_norm(alias)
  if key in mapped: return mapped[key]
 for key,value in mapped.items():
  if any(_norm(a) in key for a in aliases): return value
 return None

def parse_date(value:Any)->str:
 s=str(value or "").strip()
 m=re.search(r"(\d{2,4})年?[/.-]?(\d{1,2})月?[/.-]?(\d{1,2})日?",s)
 if not m: raise ValueError(f"無法辨識除權息日期：{value!r}")
 y,mo,d=map(int,m.groups())
 if y<1911: y+=1911
 return date(y,mo,d).isoformat()

def _number(value:Any)->float|None:
 if value is None: return None
 s=re.sub(r"[,，元\s]", "", str(value)).strip()
 if not s or s in {"-","--","N/A","NA"}: return None
 try: return float(s)
 except ValueError: return None

def unpack(payload:Any)->list[dict]:
 if isinstance(payload,list):
  if not payload: return []
  if isinstance(payload[0],dict): return payload
  raise ValueError("官方資料陣列不是物件格式")
 if isinstance(payload,dict):
  if isinstance(payload.get("data"),list):
   data=payload["data"]
   fields=payload.get("fields") or payload.get("field") or []
   if data and isinstance(data[0],dict): return data
   if fields and data:
    return [dict(zip(fields,row)) for row in data if isinstance(row,(list,tuple))]
  for key in ("result","records","items"):
   if isinstance(payload.get(key),list): return unpack(payload[key])
 raise ValueError("官方 API 回傳格式不符合預期或沒有資料")

def normalize(row:dict,market:str)->dict|None:
 stock=str(_pick(row,["股票代號","證券代號","代號","Code","Stock Code","股票代碼"]) or "").strip()
 stock=stock.replace(".TW","").replace(".TWO","")
 if stock not in TARGETS[market]: return None
 raw_date=_pick(row,["除權息日期","資料日期","除權日期","日期","Date"])
 ex_date=parse_date(raw_date)
 prev=_number(_pick(row,["除權息前收盤價","除權息前一日收盤價","前收盤價","除權前收盤價","Previous Close"]))
 ref=_number(_pick(row,["除權息參考價","除權參考價","開始交易基準價","參考價","Reference Price"]))
 kind=str(_pick(row,["權/息","權或息","除權息","類別","權息別","Type"]) or "").strip()
 if prev is None or ref is None or prev<=0 or ref<=0:
  raise ValueError(f"{market} {stock} {ex_date} 缺少有效前收盤價/參考價")
 if "息" in kind and "權" not in kind:
  action_type="CASH_DIVIDEND"; verified=True; share_factor=1.0
  notes="官方計算結果標示為純除息；價格係數採除權息參考價/前收盤價"
 else:
  action_type="STOCK_DIVIDEND" if "權" in kind and "息" not in kind else "OTHER"
  verified=False; share_factor=1.0
  notes="含除權或混合事件；等待公告配股比例及股數轉換資料核對，不自動套用"
 price_factor=ref/prev if verified else 1.0
 raw_json=json.dumps(row,ensure_ascii=False,sort_keys=True,default=str)
 key=hashlib.sha256(f"{market}|{stock}|{ex_date}|{raw_json}".encode()).hexdigest()
 return {"market":market,"stock_id":stock,"ex_date":ex_date,"action_type":action_type,
         "price_factor":price_factor,"share_factor":share_factor,"source":"TWSE_TWT49U" if market=="twse" else "TPEx_tpex_exright_daily",
         "source_event_id":key,"verified":verified,"notes":notes,"raw_data":raw_json}

def fetch_twse(start_date:str,end_date:str)->list[dict]:
 r=requests.get(TWSE_URL,params={"startDate":start_date.replace("-",""),"endDate":end_date.replace("-",""),"response":"json"},timeout=(15,60))
 r.raise_for_status(); payload=r.json()
 if str(payload.get("stat","")).lower() not in {"ok","success",""}:
  raise RuntimeError(f"TWSE API status: {payload.get('stat')}")
 return unpack(payload)

def fetch_tpex()->list[dict]:
 r=requests.get(TPEX_URL,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"},timeout=(15,60))
 r.raise_for_status()
 return unpack(r.json())

def main():
 p=argparse.ArgumentParser()
 p.add_argument("--start-date",default="2021-01-01")
 p.add_argument("--end-date",default=date.today().isoformat())
 p.add_argument("--market",choices=("twse","tpex","both"),default="both")
 a=p.parse_args()
 url=os.environ.get("DATABASE_URL")
 if not url: raise RuntimeError("缺少 DATABASE_URL")
 rows=[]
 if a.market in ("twse","both"):
  for row in fetch_twse(a.start_date,a.end_date):
   item=normalize(row,"twse")
   if item: rows.append(item)
 if a.market in ("tpex","both"):
  for row in fetch_tpex():
   item=normalize(row,"tpex")
   if item: rows.append(item)
 if not rows:
  raise RuntimeError("官方資料未回傳目標股票事件；不寫入空資料")
 sql="""INSERT INTO corporate_actions
 (market,stock_id,ex_date,action_type,price_factor,share_factor,source,source_event_id,verified,notes,raw_data)
 VALUES (%(market)s,%(stock_id)s,%(ex_date)s,%(action_type)s,%(price_factor)s,%(share_factor)s,%(source)s,%(source_event_id)s,%(verified)s,%(notes)s,%(raw_data)s::jsonb)
 ON CONFLICT (market,stock_id,ex_date,source_event_id) DO UPDATE SET
 action_type=EXCLUDED.action_type,price_factor=EXCLUDED.price_factor,
 share_factor=EXCLUDED.share_factor,verified=EXCLUDED.verified,
 notes=EXCLUDED.notes,raw_data=EXCLUDED.raw_data"""
 with psycopg.connect(url,connect_timeout=20) as conn:
  with conn.cursor() as cur: cur.executemany(sql,rows)
 verified=sum(bool(x["verified"]) for x in rows)
 log.info("公司行動匯入 %d 筆；自動核實 %d 筆；待人工核對 %d 筆",len(rows),verified,len(rows)-verified)
 for x in rows: log.info("%s %s %s %s verified=%s",x["market"],x["stock_id"],x["ex_date"],x["action_type"],x["verified"])

if __name__=="__main__": main()
