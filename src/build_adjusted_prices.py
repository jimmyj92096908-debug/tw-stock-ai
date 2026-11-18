"""Build split/dividend-adjusted bars for stocks with verified corporate actions."""
from __future__ import annotations
import argparse, os
import psycopg
from psycopg.rows import dict_row
from adjusted_prices import adjust_bars

UPSERT="""
INSERT INTO daily_adjusted_prices
(market,stock_id,trade_date,open,high,low,close,volume,turnover,price_change,transactions,
 price_adjustment_factor,share_adjustment_factor,adjustment_status)
VALUES (%(market)s,%(stock_id)s,%(trade_date)s,%(open)s,%(high)s,%(low)s,%(close)s,%(volume)s,
 %(turnover)s,%(price_change)s,%(transactions)s,%(price_adjustment_factor)s,
 %(share_adjustment_factor)s,%(adjustment_status)s)
ON CONFLICT (market,stock_id,trade_date) DO UPDATE SET
 open=EXCLUDED.open,high=EXCLUDED.high,low=EXCLUDED.low,close=EXCLUDED.close,
 volume=EXCLUDED.volume,turnover=EXCLUDED.turnover,price_change=EXCLUDED.price_change,
 transactions=EXCLUDED.transactions,price_adjustment_factor=EXCLUDED.price_adjustment_factor,
 share_adjustment_factor=EXCLUDED.share_adjustment_factor,
 adjustment_status=EXCLUDED.adjustment_status,calculated_at=NOW()
"""
def build(conn, market, stock_id):
 with conn.cursor() as cur:
  cur.execute("SELECT market,stock_id,trade_date,open,high,low,close,volume,turnover,price_change,transactions FROM daily_prices WHERE market=%s AND stock_id=%s ORDER BY trade_date",(market,stock_id))
  bars=cur.fetchall()
  cur.execute("SELECT ex_date,action_type,price_factor,share_factor,cash_amount,stock_amount FROM corporate_actions WHERE market=%s AND stock_id=%s AND verified=TRUE ORDER BY ex_date",(market,stock_id))
  actions=cur.fetchall()
 if not bars: return 0
 adjusted=adjust_bars(bars,actions)
 with conn.transaction():
  with conn.cursor() as cur: cur.executemany(UPSERT,adjusted)
 return len(adjusted)
def main():
 p=argparse.ArgumentParser()
 p.add_argument("--market",choices=("twse","tpex","both"),default="both")
 p.add_argument("--stock-ids",nargs="*",default=["6213","4919","7827","8937"])
 a=p.parse_args()
 url=os.environ.get("DATABASE_URL")
 if not url: raise RuntimeError("缺少 DATABASE_URL")
 markets=("twse","tpex") if a.market=="both" else (a.market,)
 with psycopg.connect(url,row_factory=dict_row,connect_timeout=20) as conn:
  with conn.cursor() as cur:
   stocks=[]
   for m in markets:
    cur.execute("SELECT DISTINCT stock_id FROM daily_prices WHERE market=%s AND stock_id=ANY(%s) ORDER BY stock_id",(m,a.stock_ids))
    stocks.extend((m,r["stock_id"]) for r in cur.fetchall())
  if not stocks: raise RuntimeError("找不到指定股票的原始行情")
  for m,sid in stocks: print(f"{m} {sid}: {build(conn,m,sid)} rows")
if __name__=="__main__": main()
