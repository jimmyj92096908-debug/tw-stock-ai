"""Compare each tested strategy with stock buy-and-hold and TAIEX; attribute trades by TAIEX regime."""
from __future__ import annotations
import os, psycopg
from tdcc_data import normalize_database_url

def regime_map(index_rows):
    """Map each session to the regime known at the PREVIOUS session close."""
    closes=[(r[0],float(r[1])) for r in index_rows]
    out={}
    ma=[]
    for i,(d,c) in enumerate(closes):
        ma.append(sum(x[1] for x in closes[max(0,i-199):i+1])/min(i+1,200))
        if i==0:
            continue
        target_date=closes[i][0]
        prior_close=closes[i-1][1]
        prior_ma=ma[i-1]
        prior_slope=(ma[i-1]-ma[i-21]) if i>=21 else None
        if i-1<219 or prior_slope is None:
            out[target_date]="UNKNOWN"
        elif prior_close>prior_ma and prior_slope>0:
            out[target_date]="BULL"
        elif prior_close<prior_ma and prior_slope<0:
            out[target_date]="BEAR"
        else:
            out[target_date]="SIDEWAYS"
    return out

def pf(trades):
    gp=sum(float(t[1]) for t in trades if float(t[1])>0)
    gl=-sum(float(t[1]) for t in trades if float(t[1])<0)
    return gp/gl if gl else (999.0 if gp else None)

def main():
    label=os.getenv("BACKTEST_LABEL","out_of_sample")
    with psycopg.connect(normalize_database_url(os.environ["DATABASE_URL"])) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT run_id,config->>'evaluation_start',config->>'evaluation_end' FROM strategy_backtest_runs WHERE config->>'evaluation_type'=%s ORDER BY run_id DESC LIMIT 1",(label,))
            found=cur.fetchone()
            if not found: raise RuntimeError(f"No backtest run for label {label}")
            run_id,start,end=found
            cur.execute("SELECT trade_date,close FROM market_index_prices WHERE index_code='TAIEX' ORDER BY trade_date")
            regimes=regime_map(cur.fetchall())
            cur.execute("""SELECT market,stock_id,horizon,trades,wins,net_profit,total_return_pct,data_start,data_end
                FROM strategy_backtest_summary WHERE run_id=%s""",(run_id,))
            summaries=cur.fetchall()
            for market,stock,horizon,ntrades,wins,pnl,strategy_return,ds,de in summaries:
                cur.execute("""SELECT trade_date,open,close FROM daily_adjusted_prices
                    WHERE market=%s AND stock_id=%s AND trade_date BETWEEN %s AND %s
                    ORDER BY trade_date""",(market,stock,start,end))
                bars=cur.fetchall()
                stock_return=None
                if len(bars)>=2 and bars[0][1] is not None and bars[-1][2] is not None:
                    buy=float(bars[0][1])*(1+0.001)
                    sell=float(bars[-1][2])*(1-0.001)
                    cost=buy*(1+0.001425)
                    proceeds=sell*(1-0.001425-0.003)
                    stock_return=(proceeds/cost-1)*100
                taiex_return=None
                if bars:
                    dates=[d for d,_,_ in bars]
                    cur.execute("""SELECT trade_date,close FROM market_index_prices
                        WHERE index_code='TAIEX' AND trade_date BETWEEN %s AND %s ORDER BY trade_date""",(dates[0],dates[-1]))
                    idx=cur.fetchall()
                    if len(idx)>=2: taiex_return=(float(idx[-1][1])/float(idx[0][1])-1)*100
                cur.execute("""INSERT INTO strategy_backtest_benchmark_summary
                    (run_id,market,stock_id,horizon,strategy_return_pct,stock_buy_hold_return_pct,taiex_return_pct,
                     strategy_excess_vs_stock_pct,strategy_excess_vs_taiex_pct,data_start,data_end)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(run_id,market,stock_id,horizon) DO UPDATE SET
                     strategy_return_pct=EXCLUDED.strategy_return_pct,
                     stock_buy_hold_return_pct=EXCLUDED.stock_buy_hold_return_pct,
                     taiex_return_pct=EXCLUDED.taiex_return_pct,
                     strategy_excess_vs_stock_pct=EXCLUDED.strategy_excess_vs_stock_pct,
                     strategy_excess_vs_taiex_pct=EXCLUDED.strategy_excess_vs_taiex_pct,
                     data_start=EXCLUDED.data_start,data_end=EXCLUDED.data_end""",
                    (run_id,market,stock,horizon,float(strategy_return),
                     stock_return,taiex_return,
                     float(strategy_return)-stock_return if stock_return is not None else None,
                     float(strategy_return)-taiex_return if taiex_return is not None else None,ds,de))
            cur.execute("SELECT market,stock_id,horizon,entry_date,pnl FROM strategy_backtest_trades WHERE run_id=%s",(run_id,))
            grouped={}
            for market,stock,horizon,entry,pnl in cur.fetchall():
                regime=regimes.get(entry,"UNKNOWN")
                grouped.setdefault((horizon,regime),[]).append((entry,float(pnl)))
            cur.execute("DELETE FROM strategy_backtest_regime_summary WHERE run_id=%s",(run_id,))
            for horizon in ("short","swing","long"):
                for regime in ("BULL","BEAR","SIDEWAYS","UNKNOWN"):
                    ts=grouped.get((horizon,regime),[])
                    vals=[(d,p) for d,p in ts]
                    wins=sum(p>0 for _,p in vals)
                    cur.execute("""INSERT INTO strategy_backtest_regime_summary
                        (run_id,horizon,market_regime,trades,wins,win_rate,net_profit,profit_factor)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (run_id,horizon,regime,len(vals),wins,
                         wins/len(vals)*100 if vals else None,sum(p for _,p in vals),pf(vals)))
    print(f"Benchmark and TAIEX regime analysis complete: run_id={run_id}, label={label}")
if __name__=="__main__": main()
