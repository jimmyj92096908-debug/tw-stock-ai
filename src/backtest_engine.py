"""Historical, next-session-open backtest for the four configured Taiwan stocks.
Signals are calculated after each close and executed no earlier than next session open.
Long-only, one position per stock/horizon, ATR-based sizing, board-lot rounding.
"""
from __future__ import annotations
import json, math, os
from datetime import date
import psycopg
try:
    from composite_score import horizon_technical_score, horizon_smc_score, combine_scores, HORIZON_WEIGHTS, HORIZONS
except ModuleNotFoundError:
    from src.composite_score import horizon_technical_score, horizon_smc_score, combine_scores, HORIZON_WEIGHTS, HORIZONS

STOCKS=(("twse","6213"),("tpex","8937"),("twse","4919"),("twse","7827"))
HOLD_DAYS={"short":5,"swing":20,"long":60}
ENTRY_SCORE=60.0
EXIT_SCORE=45.0
RISK_FRACTION=0.01
ATR_MULTIPLE=2.0
STARTING_CAPITAL=1_000_000.0
LOT_SIZE=1000
COMMISSION_RATE=0.001425
SELL_TAX_RATE=0.003
SLIPPAGE_RATE=0.001

def signal_score(row,horizon):
    tech,ts=horizon_technical_score(row,horizon)
    smc,ss=horizon_smc_score(row,horizon)
    score,cov=combine_scores({"technical":tech,"smc":smc,"chip":None},weights=HORIZON_WEIGHTS)
    return score,cov,{"technical":ts,"smc":ss}

def position_size(equity, entry, atr):
    stop_distance=ATR_MULTIPLE*atr
    if stop_distance<=0 or entry<=0: return 0
    risk_budget=equity*RISK_FRACTION
    shares=int(risk_budget/stop_distance/LOT_SIZE)*LOT_SIZE
    affordable=int(equity/(entry*(1+SLIPPAGE_RATE)*(1+COMMISSION_RATE))/LOT_SIZE)*LOT_SIZE
    return max(0,min(shares,affordable))

def trade_costs(buy_price,sell_price,shares):
    buy_value=buy_price*shares
    sell_value=sell_price*shares
    buy_fee=buy_value*COMMISSION_RATE
    sell_fee=sell_value*COMMISSION_RATE
    tax=sell_value*SELL_TAX_RATE
    return buy_value+buy_fee, sell_value-sell_fee-tax

def simulate_stock(rows,horizon,starting_capital=STARTING_CAPITAL):
    rows=sorted(rows,key=lambda r:r["trade_date"])
    scored=[]
    for r in rows:
        score,cov,detail=signal_score(r,horizon)
        scored.append({**r,"score":score,"coverage":cov,"score_detail":detail})
    equity=float(starting_capital); peak=equity; max_dd=0.0
    trades=[]; position=None; equity_points=[]
    for i,row in enumerate(scored):
        # Manage an existing position using today's intraday range and close signal.
        if position:
            exit_price=None; exit_reason=None
            op,lo=row.get("open"),row.get("low")
            stop=position["stop_price"]
            if op is not None and float(op)<=stop:
                exit_price=float(op); exit_reason="GAP_STOP"
            elif lo is not None and float(lo)<=stop:
                exit_price=stop; exit_reason="ATR_STOP"
            elif position["holding_days"]>=HOLD_DAYS[horizon]:
                exit_price=float(op) if op is not None else None; exit_reason="MAX_HOLD"
            elif row["score"] is not None and row["score"]<=EXIT_SCORE:
                exit_price=float(op) if op is not None else None; exit_reason="SCORE_EXIT"
            if exit_price is not None:
                sell_fill=exit_price*(1-SLIPPAGE_RATE)
                net_sell= sell_fill*position["shares"]*(1-COMMISSION_RATE-SELL_TAX_RATE)
                pnl=net_sell-position["entry_cost"]
                equity+=pnl
                trades.append({"entry_date":position["entry_date"],"exit_date":row["trade_date"],
                    "entry_price":position["entry_price"],"exit_price":sell_fill,"shares":position["shares"],
                    "pnl":pnl,"return_pct":pnl/position["entry_cost"]*100,
                    "holding_days":position["holding_days"],"entry_score":position["entry_score"],
                    "exit_reason":exit_reason,"planned_risk":position["risk_budget"]})
                position=None
        # If flat, enter on next session open based only on this session's closing signal.
        if position is None and i+1<len(scored) and row["score"] is not None and row["score"]>=ENTRY_SCORE:
            nxt=scored[i+1]
            atr=row.get("atr14")
            entry_open=nxt.get("open")
            if atr is not None and entry_open is not None and float(atr)>0 and float(entry_open)>0:
                buy_fill=float(entry_open)*(1+SLIPPAGE_RATE)
                shares=position_size(equity,buy_fill,float(atr))
                if shares>0:
                    gross=buy_fill*shares
                    fee=gross*COMMISSION_RATE
                    entry_cost=gross+fee
                    stop=buy_fill-ATR_MULTIPLE*float(atr)
                    position={"entry_date":nxt["trade_date"],"entry_price":buy_fill,
                        "shares":shares,"entry_cost":entry_cost,"stop_price":stop,
                        "entry_score":row["score"],"holding_days":0,
                        "risk_budget":equity*RISK_FRACTION}
        if position:
            # Count actual trading sessions from entry day.
            if row["trade_date"]>=position["entry_date"]:
                position["holding_days"]+=1
        marked_equity=equity
        if position and row.get("close") is not None:
            mark_sell=float(row["close"])*(1-SLIPPAGE_RATE)
            mark_net=mark_sell*position["shares"]*(1-COMMISSION_RATE-SELL_TAX_RATE)
            marked_equity += mark_net-position["entry_cost"]
        peak=max(peak,marked_equity)
        max_dd=max(max_dd,(peak-marked_equity)/peak if peak else 0)
        equity_points.append(marked_equity)
    # Liquidate any remaining position at the final available close.
    if position and scored:
        last=scored[-1]; close=last.get("close")
        if close is not None:
            sell_fill=float(close)*(1-SLIPPAGE_RATE)
            net_sell=sell_fill*position["shares"]*(1-COMMISSION_RATE-SELL_TAX_RATE)
            pnl=net_sell-position["entry_cost"]; equity+=pnl
            trades.append({"entry_date":position["entry_date"],"exit_date":last["trade_date"],
                "entry_price":position["entry_price"],"exit_price":sell_fill,"shares":position["shares"],
                "pnl":pnl,"return_pct":pnl/position["entry_cost"]*100,
                "holding_days":position["holding_days"],"entry_score":position["entry_score"],
                "exit_reason":"END_OF_DATA","planned_risk":position["risk_budget"]})
    wins=sum(t["pnl"]>0 for t in trades)
    gross_profit=sum(t["pnl"] for t in trades if t["pnl"]>0)
    gross_loss=-sum(t["pnl"] for t in trades if t["pnl"]<0)
    days=(scored[-1]["trade_date"]-scored[0]["trade_date"]).days if len(scored)>1 else 0
    years=days/365.25
    total_return=(equity/starting_capital-1)*100
    cagr=((equity/starting_capital)**(1/years)-1)*100 if years>0 and equity>0 else None
    summary={"trades":len(trades),"wins":wins,"losses":len(trades)-wins,
        "win_rate":wins/len(trades)*100 if trades else None,
        "net_profit":equity-starting_capital,"total_return_pct":total_return,"cagr_pct":cagr,
        "profit_factor":gross_profit/gross_loss if gross_loss>0 else (None if gross_profit==0 else 999.0),
        "max_drawdown_pct":max_dd*100,"ending_equity":equity,
        "avg_trade_pct":sum(t["return_pct"] for t in trades)/len(trades) if trades else None,
        "data_start":str(scored[0]["trade_date"]) if scored else None,
        "data_end":str(scored[-1]["trade_date"]) if scored else None}
    return summary,trades

def load_rows(cur,market,stock_id):
    cur.execute("""SELECT a.trade_date,a.open,a.high,a.low,a.close,a.volume,t.ma5,t.ma10,t.ma13,t.ma20,
        t.ma34,t.ma55,t.ma60,t.ma120,t.ma240,t.rsi14,t.volume_ma5,t.volume_ma20,t.atr14,
        s.trend_direction,s.bos_bullish,s.bos_bearish,s.choch_bullish,s.choch_bearish,
        s.liquidity_sweep_high,s.liquidity_sweep_low,s.order_block_type,s.fvg_type
        FROM daily_adjusted_prices a
        LEFT JOIN daily_technicals t USING(market,stock_id,trade_date)
        LEFT JOIN daily_smc s USING(market,stock_id,trade_date)
        WHERE a.market=%s AND a.stock_id=%s ORDER BY a.trade_date""",(market,stock_id))
    cols=[d.name for d in cur.description]
    return [dict(zip(cols,row)) for row in cur.fetchall()]

def run(database_url):
    results=[]; all_trades=[]
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            for market,stock_id in STOCKS:
                rows=load_rows(cur,market,stock_id)
                for horizon in HOLD_DAYS:
                    summary,trades=simulate_stock(rows,horizon)
                    results.append((market,stock_id,horizon,summary))
                    all_trades.extend((market,stock_id,horizon,t) for t in trades)
            cur.execute("INSERT INTO backtest_runs(config) VALUES (%s::jsonb) RETURNING run_id",
                (json.dumps({"entry_score":ENTRY_SCORE,"exit_score":EXIT_SCORE,"risk_fraction":RISK_FRACTION,
                 "atr_multiple":ATR_MULTIPLE,"holding_days":HOLD_DAYS,"starting_capital_per_stock":STARTING_CAPITAL,
                 "lot_size":LOT_SIZE,"commission_rate":COMMISSION_RATE,"sell_tax_rate":SELL_TAX_RATE,
                 "slippage_rate_each_side":SLIPPAGE_RATE,"execution":"next_session_open"},ensure_ascii=False),))
            run_id=cur.fetchone()[0]
            for market,stock_id,horizon,s in results:
                cur.execute("""INSERT INTO backtest_summary
                    (run_id,market,stock_id,horizon,trades,wins,losses,win_rate,net_profit,total_return_pct,
                     cagr_pct,profit_factor,max_drawdown_pct,ending_equity,avg_trade_pct,data_start,data_end,metrics)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                    (run_id,market,stock_id,horizon,s["trades"],s["wins"],s["losses"],s["win_rate"],s["net_profit"],
                     s["total_return_pct"],s["cagr_pct"],s["profit_factor"],s["max_drawdown_pct"],s["ending_equity"],
                     s["avg_trade_pct"],s["data_start"],s["data_end"],json.dumps(s,ensure_ascii=False)))
            for market,stock_id,horizon,t in all_trades:
                cur.execute("""INSERT INTO backtest_trades
                    (run_id,market,stock_id,horizon,entry_date,exit_date,entry_price,exit_price,shares,pnl,
                     return_pct,holding_days,entry_score,exit_reason,planned_risk)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (run_id,market,stock_id,horizon,t["entry_date"],t["exit_date"],t["entry_price"],t["exit_price"],
                     t["shares"],t["pnl"],t["return_pct"],t["holding_days"],t["entry_score"],t["exit_reason"],t["planned_risk"]))
    print("BACKTEST_RUN_ID",run_id)
    for market,stock_id,horizon,s in results:
        print(market,stock_id,horizon,json.dumps(s,ensure_ascii=False,default=str))
    return run_id

if __name__=="__main__":
    from tdcc_data import normalize_database_url
    run(normalize_database_url(os.environ["DATABASE_URL"]))
