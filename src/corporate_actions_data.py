"""Import official TWSE/TPEx ex-right, ex-dividend and capital-reduction records.

Cash-only events and capital reductions with an explicit official share-conversion
ratio can be verified automatically. Rights/mixed events without complete ratios
are stored as unverified and are excluded from adjusted prices.
"""
from __future__ import annotations
import argparse, hashlib, json, logging, os, re
from datetime import date
from typing import Any
import requests
import psycopg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger(__name__)
TWSE_EX_URL="https://www.twse.com.tw/rwd/zh/exRight/TWT49U"
TWSE_REDUCTION_URL="https://www.twse.com.tw/exchangeReport/TWTAUU"
TPEX_EX_URL="https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ"
TPEX_REDUCTION_URL="https://www.tpex.org.tw/www/zh-tw/bulletin/revivt"
TPEX_EX_LEGACY_URL="https://www.tpex.org.tw/web/stock/exright/dailyquo/exDailyQ_result.php"
TPEX_EX_COLUMNS=["除權息日期","代號","名稱","除權息前收盤價","除權息參考價","權值","息值","權值加息值","權或息","漲停價","跌停價","開始交易基準價","減除股利參考價","現金股利","每仟股無償配股","現金增資股數","現金增資認購價","公開承銷股數","員工認購股數","原股東認購股數","按持股比例仟股認購"]
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
 if not m: raise ValueError(f"無法辨識公司行動日期：{value!r}")
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
   data=payload["data"]; fields=payload.get("fields") or payload.get("field") or []
   if data and isinstance(data[0],dict): return data
   if fields and data: return [dict(zip(fields,row)) for row in data if isinstance(row,(list,tuple))]
  if isinstance(payload.get("aaData"),list):
   rows=payload["aaData"]
   if rows and isinstance(rows[0],dict): return rows
   if rows: return [dict(zip(TPEX_EX_COLUMNS,row)) for row in rows if isinstance(row,(list,tuple))]
  for key in ("result","records","items"):
   if isinstance(payload.get(key),list): return unpack(payload[key])
 raise ValueError("官方 API 回傳格式不符合預期")

def _base_record(row:dict,market:str,event_date:Any,stock:Any,prev:Any,ref:Any,
                 action_type:str,price_factor:float,share_factor:float,verified:bool,
                 source:str,notes:str)->dict|None:
 sid=str(stock or "").strip().replace(".TW","").replace(".TWO","")
 if sid not in TARGETS[market]: return None
 d=parse_date(event_date); p=_number(prev); r=_number(ref)
 if p is None or r is None or p<=0 or r<=0:
  raise ValueError(f"{market} {sid} {d} 缺少有效參考價")
 raw_json=json.dumps(row,ensure_ascii=False,sort_keys=True,default=str)
 key=hashlib.sha256(f"{market}|{sid}|{d}|{source}|{raw_json}".encode()).hexdigest()
 return {"market":market,"stock_id":sid,"ex_date":d,"action_type":action_type,
  "price_factor":price_factor,"share_factor":share_factor,"source":source,
  "source_event_id":key,"verified":verified,"notes":notes,"raw_data":raw_json}

def normalize(row:dict,market:str)->dict|None:
 stock=_pick(row,["股票代號","證券代號","代號","Code","Stock Code","股票代碼"])
 if str(stock or "").strip() not in TARGETS[market]: return None
 event_date=_pick(row,["除權息日期","資料日期","除權日期","日期","Date"])
 prev=_pick(row,["除權息前收盤價","除權息前一日收盤價","前收盤價","除權前收盤價","Previous Close"])
 ref=_pick(row,["除權息參考價","除權參考價","開始交易基準價","參考價","Reference Price"])
 kind=str(_pick(row,["權/息","權或息","除權息","類別","權息別","Type"]) or "").strip()
 p=_number(prev); r=_number(ref)
 if p is None or r is None or p<=0 or r<=0: raise ValueError(f"{market} {stock} 缺少除權息價格")
 if "息" in kind and "權" not in kind:
  return _base_record(row,market,event_date,stock,prev,ref,"CASH_DIVIDEND",r/p,1.0,True,
    "TWSE_TWT49U" if market=="twse" else "TPEx_exDailyQ",
    "官方計算結果為純除息；係數=參考價/前收盤價")
 return _base_record(row,market,event_date,stock,prev,ref,
   "STOCK_DIVIDEND" if "權" in kind and "息" not in kind else "OTHER",
   1.0,1.0,False,"TWSE_TWT49U" if market=="twse" else "TPEx_exDailyQ",
   "除權或權息混合事件；缺少完整換股比例，待核對")

def normalize_reduction(row:dict,market:str)->dict|None:
 stock=_pick(row,["股票代號","證券代號","代號","Code"])
 if str(stock or "").strip() not in TARGETS[market]: return None
 event_date=_pick(row,["恢復買賣日期","恢復交易日期","日期","Resume Date"])
 prev=_pick(row,["停止買賣前收盤價","最後交易日之收盤價格","停止買賣前收盤價格","前收盤價"])
 ref=_pick(row,["恢復買賣參考價","減資恢復買賣開始日參考價格","恢復買賣開始日參考價格","參考價"])
 shares=_number(_pick(row,["每仟股換發股數","每千股換發股數","原股票每千股換發新股票","減資換股率","sharesPerThousand"]))
 p=_number(prev); r=_number(ref)
 if p is None or r is None or p<=0 or r<=0: raise ValueError(f"{market} {stock} 減資事件缺少有效參考價")
 if shares is not None and 0<shares<=1000:
  sf=shares/1000.0; verified=True
  notes="官方減資恢復買賣資料含每千股換發股數；價格及股數係數依官方參考價與換股率"
 else:
  sf=1.0; verified=False
  notes="官方減資參考價已取得，但資料列未提供可核實換股率；暫不套用"
 return _base_record(row,market,event_date,stock,prev,ref,"CAPITAL_REDUCTION",
  r/p if verified else 1.0,sf,verified,
  "TWSE_TWTAUU" if market=="twse" else "TPEx_revivt",notes)

def _get(url:str,params:dict)->list[dict]:
 r=requests.get(url,params=params,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"},timeout=(15,60))
 r.raise_for_status()
 return unpack(r.json())

def _roc_date(iso_date:str)->str:
 y,m,d=map(int,iso_date.split("-"))
 return f"{y-1911}/{m:02d}/{d:02d}"

def _fetch_tpex_ex_rows(start_date:str,end_date:str)->list[dict]:
 # Prefer current TPEx historical endpoint; fall back when it fails or returns no rows.
 try:
  rows=_get(TPEX_EX_URL,{"startDate":start_date.replace("-","/"),
                         "endDate":end_date.replace("-","/"),"response":"json"})
  if rows: return rows
 except Exception as exc:
  log.warning("TPEx 新版除權息端點失敗，改用歷史查詢端點：%s",exc)
 return _get(TPEX_EX_LEGACY_URL,{"l":"zh-tw","d":_roc_date(start_date),
                                "ed":_roc_date(end_date)})

def fetch_market(market:str,start_date:str,end_date:str)->list[dict]:
 start=start_date.replace("-",""); end=end_date.replace("-","")
 if market=="twse":
  ex_rows=_get(TWSE_EX_URL,{"startDate":start,"endDate":end,"response":"json"})
  red_rows=_get(TWSE_REDUCTION_URL,{"startDate":start,"endDate":end,"response":"json"})
 else:
  # TPEx historical web endpoints accept Gregorian YYYY/MM/DD, unlike OpenAPI snapshots.
  start_slash=start_date.replace("-","/"); end_slash=end_date.replace("-","/")
  ex_rows=_fetch_tpex_ex_rows(start_date,end_date)
  red_rows=_get(TPEX_REDUCTION_URL,{"startDate":start_slash,"endDate":end_slash,"response":"json"})
 output=[]
 for row in ex_rows:
  item=normalize(row,market)
  if item: output.append(item)
 for row in red_rows:
  item=normalize_reduction(row,market)
  if item: output.append(item)
 return output

def main():
 p=argparse.ArgumentParser()
 p.add_argument("--start-date",default="2021-01-01")
 p.add_argument("--end-date",default=date.today().isoformat())
 p.add_argument("--market",choices=("twse","tpex","both"),default="both")
 a=p.parse_args(); url=os.environ.get("DATABASE_URL")
 if not url: raise RuntimeError("缺少 DATABASE_URL")
 rows=[]
 markets=("twse","tpex") if a.market=="both" else (a.market,)
 errors=[]
 for market in markets:
  try:
   batch=fetch_market(market,a.start_date,a.end_date)
   rows.extend(batch); log.info("%s 官方來源取得 %d 筆目標公司行動",market,len(batch))
  except Exception as exc:
   errors.append(f"{market}: {exc}"); log.exception("%s 公司行動來源失敗",market)
 if not rows: raise RuntimeError("兩市場均未取得目標事件；"+ "; ".join(errors))
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
 log.info("匯入 %d 筆；核實 %d 筆；待核對 %d 筆",len(rows),verified,len(rows)-verified)
 if errors: log.warning("部分來源失敗：%s","; ".join(errors))
 for x in rows: log.info("%s %s %s %s verified=%s",x["market"],x["stock_id"],x["ex_date"],x["action_type"],x["verified"])

if __name__=="__main__": main()
