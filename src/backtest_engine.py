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
try:
    from regime_classifier import regime_map
except ModuleNotFoundError:
    from src.regime_classifier import regime_map

STOCKS=(("twse","6213"),("tpex","8937"),("twse","4919"),("twse","7827"))
HOLD_DAYS={"short":5,"swing":20,"long":60}
ENTRY_SCORE=float(os.getenv("BACKTEST_ENTRY_SCORE","60"))
EXIT_SCORE=45.0
RISK_FRACTION=0.01
ATR_MULTIPLE=float(os.getenv("BACKTEST_ATR_MULTIPLE","2.0"))
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
    stop_price=max(0.0,entry-stop_distance)
    # Include estimated entry/exit slippage, commissions and ordinary-share sell tax
    # in the 1% risk budget, not just the raw ATR stop distance.
    cost_adjusted_risk=(stop_distance + entry*SLIPPAGE_RATE + stop_price*SLIPPAGE_RATE
        + entry*COMMISSION_RATE + stop_price*(COMMISSION_RATE+SELL_TAX_RATE))
    shares=int(risk_budget/cost_adjusted_risk/LOT_SIZE)*LOT_SIZE
    affordable=int(equity/(entry*(1+SLIPPAGE_RATE)*(1+COMMISSION_RATE))/LOT_SIZE)*LOT_SIZE
    return max(0,min(shares,affordable))

def trade_costs(buy_price,sell_price,shares):
    buy_value=buy_price*shares
    sell_value=sell_price*shares
    buy_fee=buy_value*COMMISSION_RATE
    sell_fee=sell_value*COMMISSION_RATE
    tax=sell_value*SELL_TAX_RATE
    return buy_value+buy_fee, sell_value-sell_fee-tax

def simulate_stock(rows,horizon,starting_capital=STARTING_CAPITAL,start_date=None,end_date=None,regime_entry_scores=None):
    rows=sorted(rows,key=lambda r:r["trade_date"])
    scored=[]
    for r in rows:
        score,cov,detail=signal_score(r,horizon)
        scored.append({**r,"score":score,"coverage":cov,"score_detail":detail})
    equity=float(starting_capital); peak=equity; max_dd=0.0
    trades=[]; position=None; pending_entry=None
    period_rows=[r for r in scored if (start_date is None or r["trade_date"]>=start_date) and (end_date is None or r["trade_date"]<=end_date)]
    for i,row in enumerate(scored):
        if start_date is not None and row["trade_date"]<start_date: continue
        if end_date is not None and row["trade_date"]>end_date: break
        op,lo,close=row.get("open"),row.get("low"),row.get("close")
        # Orders generated at the previous close execute at today's open.
        if position:
            exit_price=None; reason=None
            if op is not None and float(op)<=position["stop_price"]:
                exit_price=float(op); reason="GAP_STOP"
            elif position.get("exit_pending"):
                exit_price=float(op) if op is not None else None
                reason=position["exit_pending"]
            elif lo is not None and float(lo)<=position["stop_price"]:
                exit_price=position["stop_price"]; reason="ATR_STOP"
            if exit_price is not None:
                sell_fill=exit_price*(1-SLIPPAGE_RATE)
                net_sell=sell_fill*position["shares"]*(1-COMMISSION_RATE-SELL_TAX_RATE)
                pnl=net_sell-position["entry_cost"]; equity+=pnl
                trades.append({"entry_date":position["entry_date"],"exit_date":row["trade_date"],
                    "entry_price":position["entry_price"],"exit_price":sell_fill,"shares":position["shares"],
                    "pnl":pnl,"return_pct":pnl/position["entry_cost"]*100,
                    "holding_days":position["holding_days"],"entry_score":position["entry_score"],
                    "exit_reason":reason,"planned_risk":position["risk_budget"]})
                position=None
        if position is None and pending_entry and op is not None:
            atr=pending_entry["atr"]
            buy_fill=float(op)*(1+SLIPPAGE_RATE)
            shares=position_size(equity,buy_fill,atr)
            if shares>0:
                gross=buy_fill*shares
                position={"entry_date":row["trade_date"],"entry_price":buy_fill,"shares":shares,
                    "entry_cost":gross*(1+COMMISSION_RATE),
                    "stop_price":buy_fill-ATR_MULTIPLE*atr,
                    "entry_score":pending_entry["score"],"holding_days":0,
                    "risk_budget":equity*RISK_FRACTION}
            pending_entry=None
            # A newly opened position is exposed to the entry session's low.
            if position and lo is not None and float(lo)<=position["stop_price"]:
                sell_fill=position["stop_price"]*(1-SLIPPAGE_RATE)
                net_sell=sell_fill*position["shares"]*(1-COMMISSION_RATE-SELL_TAX_RATE)
                pnl=net_sell-position["entry_cost"]; equity+=pnl
                trades.append({"entry_date":position["entry_date"],"exit_date":row["trade_date"],
                    "entry_price":position["entry_price"],"exit_price":sell_fill,"shares":position["shares"],
                    "pnl":pnl,"return_pct":pnl/position["entry_cost"]*100,
                    "holding_days":1,"entry_score":position["entry_score"],
                    "exit_reason":"ATR_STOP_ENTRY_DAY","planned_risk":position["risk_budget"]})
                position=None
        if position:
            position["holding_days"]+=1
            # Signals at today's close are only actionable at the next session open.
            if row["score"] is not None and row["score"]<=EXIT_SCORE:
                position["exit_pending"]="SCORE_EXIT"
            elif position["holding_days"]>=HOLD_DAYS[horizon]:
                position["exit_pending"]="MAX_HOLD"
        if position and close is not None:
            mark_sell=float(close)*(1-SLIPPAGE_RATE)
            marked_equity=equity+mark_sell*position["shares"]*(1-COMMISSION_RATE-SELL_TAX_RATE)-position["entry_cost"]
        else:
            marked_equity=equity
        peak=max(peak,marked_equity)
        max_dd=max(max_dd,(peak-marked_equity)/peak if peak else 0)
        # A close-time entry signal is stored and filled on the next session only.
        if position is None and pending_entry is None and i+1<len(scored):
            if end_date is not None and scored[i+1]["trade_date"]>end_date: continue
            atr=row.get("atr14")
            required_score=(regime_entry_scores or {}).get(row.get("market_regime","UNKNOWN"),ENTRY_SCORE)
            if row["score"] is not None and row["score"]>=required_score and atr is not None and float(atr)>0:
                pending_entry={"score":row["score"],"atr":float(atr)}
    if position and period_rows and period_rows[-1].get("close") is not None:
        last=period_rows[-1]; sell_fill=float(last["close"])*(1-SLIPPAGE_RATE)
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
    # CAGR must use the actual evaluation window, not the full indicator warm-up history.
    days=(period_rows[-1]["trade_date"]-period_rows[0]["trade_date"]).days if len(period_rows)>1 else 0
    years=days/365.25
    total_return=(equity/starting_capital-1)*100
    cagr=((equity/starting_capital)**(1/years)-1)*100 if years>0 and equity>0 else None
    summary={"trades":len(trades),"wins":wins,"losses":len(trades)-wins,
        "win_rate":wins/len(trades)*100 if trades else None,
        "net_profit":equity-starting_capital,"total_return_pct":total_return,"cagr_pct":cagr,
        "profit_factor":gross_profit/gross_loss if gross_loss>0 else (None if gross_profit==0 else 999.0),
        "max_drawdown_pct":max_dd*100,"ending_equity":equity,
        "avg_trade_pct":sum(t["return_pct"] for t in trades)/len(trades) if trades else None,
        "data_start":str(period_rows[0]["trade_date"]) if period_rows else None,
        "data_end":str(period_rows[-1]["trade_date"]) if period_rows else None,
        "evaluation_days":days}
    return summary,trades

def load_rows(cur,market,stock_id,end_date=None):
    sql="""SELECT a.trade_date,a.open,a.high,a.low,a.close,a.volume,t.ma5,t.ma10,t.ma13,t.ma20,
        t.ma34,t.ma55,t.ma60,t.ma120,t.ma240,t.rsi14,t.volume_ma5,t.volume_ma20,t.atr14,
        s.trend_direction,s.bos_bullish,s.bos_bearish,s.choch_bullish,s.choch_bearish,
        s.liquidity_sweep_high,s.liquidity_sweep_low,s.order_block_type,s.fvg_type
        FROM daily_adjusted_prices a
        LEFT JOIN daily_technicals t USING(market,stock_id,trade_date)
        LEFT JOIN daily_smc s USING(market,stock_id,trade_date)
        WHERE a.market=%s AND a.stock_id=%s"""
    params=[market,stock_id]
    if end_date is not None:
        sql+=" AND a.trade_date<=%s"
        params.append(end_date)
    cur.execute(sql+" ORDER BY a.trade_date",params)
    cols=[d.name for d in cur.description]
    return [dict(zip(cols,row)) for row in cur.fetchall()]

def run(database_url):
    results=[]; all_trades=[]
    start_text=os.getenv("BACKTEST_START_DATE","2021-01-01")
    end_text=os.getenv("BACKTEST_END_DATE","2026-12-31")
    start_date=date.fromisoformat(start_text); end_date=date.fromisoformat(end_text)
    if start_date>end_date: raise ValueError("BACKTEST_START_DATE must be <= BACKTEST_END_DATE")
    regime_text=os.getenv("BACKTEST_REGIME_ENTRY_SCORES")
    regime_entry_scores=json.loads(regime_text) if regime_text else None
    if regime_entry_scores is not None:
        if not isinstance(regime_entry_scores,dict) or any(not isinstance(v,(int,float)) for v in regime_entry_scores.values()):
            raise ValueError("BACKTEST_REGIME_ENTRY_SCORES must be a JSON object of numeric thresholds")
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT trade_date,close FROM market_index_prices WHERE index_code='TAIEX' ORDER BY trade_date")
            regimes=regime_map(cur.fetchall())
            for market,stock_id in STOCKS:
                rows=load_rows(cur,market,stock_id)
                for row in rows:
                    row["market_regime"]=regimes.get(row["trade_date"],"UNKNOWN")
                for horizon in HOLD_DAYS:
                    summary,trades=simulate_stock(rows,horizon,start_date=start_date,end_date=end_date,
                                                  regime_entry_scores=regime_entry_scores)
                    results.append((market,stock_id,horizon,summary))
                    all_trades.extend((market,stock_id,horizon,t) for t in trades)
            cur.execute("INSERT INTO strategy_backtest_runs(config) VALUES (%s::jsonb) RETURNING run_id",
                (json.dumps({"entry_score":ENTRY_SCORE,"exit_score":EXIT_SCORE,"risk_fraction":RISK_FRACTION,
                 "atr_multiple":ATR_MULTIPLE,"regime_entry_scores":regime_entry_scores,
                 "holding_days":HOLD_DAYS,"starting_capital_per_stock":STARTING_CAPITAL,
                 "lot_size":LOT_SIZE,"commission_rate":COMMISSION_RATE,"sell_tax_rate":SELL_TAX_RATE,
                 "slippage_rate_each_side":SLIPPAGE_RATE,"execution":"next_session_open",
                 "evaluation_start":start_text,"evaluation_end":end_text,
                 "evaluation_type":os.getenv("BACKTEST_LABEL","unspecified")},ensure_ascii=False),))
            run_id=cur.fetchone()[0]
            for market,stock_id,horizon,s in results:
                cur.execute("""INSERT INTO strategy_backtest_summary
                    (run_id,market,stock_id,horizon,trades,wins,losses,win_rate,net_profit,total_return_pct,
                     cagr_pct,profit_factor,max_drawdown_pct,ending_equity,avg_trade_pct,data_start,data_end,metrics)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                    (run_id,market,stock_id,horizon,s["trades"],s["wins"],s["losses"],s["win_rate"],s["net_profit"],
                     s["total_return_pct"],s["cagr_pct"],s["profit_factor"],s["max_drawdown_pct"],s["ending_equity"],
                     s["avg_trade_pct"],s["data_start"],s["data_end"],json.dumps(s,ensure_ascii=False)))
            for market,stock_id,horizon,t in all_trades:
                cur.execute("""INSERT INTO strategy_backtest_trades
                    (run_id,market,stock_id,horizon,entry_date,exit_date,entry_price,exit_price,shares,pnl,
                     return_pct,holding_days,entry_score,exit_reason,planned_risk)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (run_id,market,stock_id,horizon,t["entry_date"],t["exit_date"],t["entry_price"],t["exit_price"],
                     t["shares"],t["pnl"],t["return_pct"],t["holding_days"],t["entry_score"],t["exit_reason"],t["planned_risk"]))
    print("BACKTEST_LABEL",os.getenv("BACKTEST_LABEL","unspecified"))
    print("BACKTEST_PERIOD",start_text,end_text)
    print("BACKTEST_RUN_ID",run_id)
    for market,stock_id,horizon,s in results:
        print(market,stock_id,horizon,json.dumps(s,ensure_ascii=False,default=str))
    return run_id

if __name__=="__main__":
    from tdcc_data import normalize_database_url
    run(normalize_database_url(os.environ["DATABASE_URL"]))
