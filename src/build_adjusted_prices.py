"""Build split/dividend-adjusted bars for stocks with verified corporate actions."""
from __future__ import annotations
import argparse, os
from decimal import Decimal, InvalidOperation
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
# Raw TPEx monthly CSV uses 1,000 shares / 1,000 NTD per unit.
# This is a DERIVED-series correction only; never UPDATE daily_prices.
LEGACY_TPEX_MONTHLY_SOURCE = "TPEX_TRADING_STOCK"
ALREADY_IN_SHARES_TPEX_SOURCES = {
    "TPEX_TRADING_STOCK_NORMALIZED",
    "TPEX_DAILY_CLOSE_OPENAPI",
    "TPEX_DATED_OTC_EW",
}
MAX_BIGINT = 9_223_372_036_854_775_807


def normalize_source_units(bars, market):
    """Use a per-row immutable copy; source-tagged raw TPEx monthly data only.

    Keep historical raw prices untouched. The official monthly tradingStock
    source measures 成交仟股/成交仟元; all other known TPEx sources store
    shares and NTD. Refuse unknown tags instead of guessing multiplier.
    """
    if market not in ("twse", "tpex"):
        raise ValueError("Unknown market for adjusted price normalization")
    output = []
    for bar in bars:
        item = dict(bar)
        source = item.get("source")
        if market == "tpex":
            if source == LEGACY_TPEX_MONTHLY_SOURCE:
                for field in ("volume", "turnover"):
                    value = item.get(field)
                    if value is None:
                        continue
                    try:
                        converted = Decimal(str(value)) * Decimal(1000)
                    except (InvalidOperation, ValueError) as exc:
                        raise ValueError("Invalid raw TPEx monthly unit") from exc
                    if not converted.is_finite() or converted < 0:
                        raise ValueError("Invalid raw TPEx monthly unit")
                    if field == "volume":
                        if converted != converted.to_integral_value() or converted > MAX_BIGINT:
                            raise ValueError("Invalid normalized TPEx shares")
                        item[field] = int(converted)
                    else:
                        item[field] = converted
            elif source not in ALREADY_IN_SHARES_TPEX_SOURCES:
                raise ValueError("Unknown TPEx source unit contract")
        output.append(item)
    return output


def build(conn, market, stock_id):
 with conn.cursor() as cur:
  cur.execute("SELECT market,stock_id,trade_date,open,high,low,close,volume,turnover,price_change,transactions,source FROM daily_prices WHERE market=%s AND stock_id=%s AND NOT EXISTS (SELECT 1 FROM public.model_stock_exclusions x WHERE x.market=daily_prices.market AND x.stock_id=daily_prices.stock_id) ORDER BY trade_date",(market,stock_id))
  bars=cur.fetchall()
  cur.execute("SELECT ex_date,action_type,price_factor,share_factor,cash_amount,stock_amount FROM corporate_actions WHERE market=%s AND stock_id=%s AND verified=TRUE ORDER BY ex_date",(market,stock_id))
  actions=cur.fetchall()
 if not bars: return 0
 adjusted=adjust_bars(normalize_source_units(bars,market),actions)
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
    cur.execute("SELECT DISTINCT stock_id FROM daily_prices WHERE market=%s AND stock_id=ANY(%s) AND NOT EXISTS (SELECT 1 FROM public.model_stock_exclusions x WHERE x.market=daily_prices.market AND x.stock_id=daily_prices.stock_id) ORDER BY stock_id",(m,a.stock_ids))
    stocks.extend((m,r["stock_id"]) for r in cur.fetchall())
  if not stocks: raise RuntimeError("找不到指定股票的原始行情")
  for m,sid in stocks: print(f"{m} {sid}: {build(conn,m,sid)} rows")
if __name__=="__main__": main()
