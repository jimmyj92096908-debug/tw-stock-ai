"""Development-only sensitivity study for entry-score thresholds.
Never reads the 2025+ out-of-sample window and never changes production parameters.
"""
from __future__ import annotations
import os
import psycopg
import backtest_engine as engine
from tdcc_data import normalize_database_url

CANDIDATE_THRESHOLDS=(60.0,65.0,70.0,75.0)
DEVELOPMENT_START="2021-01-01"
DEVELOPMENT_END="2024-12-31"

def main():
    url=normalize_database_url(os.environ["DATABASE_URL"])
    aggregate=[]
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            stocks=[]
            for market,stock in engine.STOCKS:
                stocks.append((market,stock,engine.load_rows(cur,market,stock)))
            for threshold in CANDIDATE_THRESHOLDS:
                engine.ENTRY_SCORE=threshold
                summaries=[]; trades=[]
                for market,stock,rows in stocks:
                    for horizon in engine.HOLD_DAYS:
                        summary,stock_trades=engine.simulate_stock(
                            rows,horizon,start_date=__import__("datetime").date.fromisoformat(DEVELOPMENT_START),
                            end_date=__import__("datetime").date.fromisoformat(DEVELOPMENT_END))
                        summaries.append(summary)
                        trades.extend(stock_trades)
                net=sum(float(s["net_profit"]) for s in summaries)
                capital=engine.STARTING_CAPITAL*len(summaries)
                gross_profit=sum(float(t["pnl"]) for t in trades if float(t["pnl"])>0)
                gross_loss=-sum(float(t["pnl"]) for t in trades if float(t["pnl"])<0)
                pf=gross_profit/gross_loss if gross_loss else (999.0 if gross_profit else None)
                max_dd=max((float(s["max_drawdown_pct"]) for s in summaries),default=0.0)
                row={"entry_score":threshold,"portfolios":len(summaries),"trades":len(trades),
                     "net_profit":round(net,2),"aggregate_return_pct":round(net/capital*100,3),
                     "profit_factor":round(pf,3) if pf is not None else None,
                     "worst_portfolio_max_drawdown_pct":round(max_dd,3)}
                aggregate.append(row)
                print("DEVELOPMENT_ONLY",row)
    print("No 2025+ rows were loaded or evaluated.")
    return aggregate

if __name__=="__main__":
    main()
