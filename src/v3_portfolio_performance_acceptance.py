"""Descriptive acceptance metrics from a simulated account, never release approval.

Use net closed episodes, money-weighted P&L profit factor, daily close equity
and entry-date block sensitivity. No independent evidence or authentic
calendar is inferred from the supplied ledger. Open episodes remain visible.
"""
from collections import defaultdict
from math import fsum,sqrt,isclose
from statistics import mean,stdev
import random
from src.v3_capital_risk_research import _num,outcome_diagnostics
from src.v3_probability_calibration import _day
from src.v3_purged_logistic_baseline import _hash


def portfolio_performance_acceptance(replay):
    path=replay["path"]
    episodes=replay["closed_position_episodes"]
    if not isinstance(path,list) or not 2<=len(path)<=2000 or not isinstance(episodes,list) or len(episodes)>200000:
        raise ValueError("Invalid bounded ledger")
    days=[_day(r["date"]) for r in path]
    if any(a>=b for a,b in zip(days,days[1:])):
        raise ValueError("Unordered account path")
    equity=[]
    for row in path:
        value=_num(row["equity"],"equity",1e-9,1e15)
        parts=[_num(row[k],k,0,1e15) for k in ("available_cash","unsettled_sale_proceeds",
                    "market_value","gross_dividend_receivable")]
        if not isclose(value,fsum(parts),rel_tol=1e-9,abs_tol=1e-6):
            raise ValueError("Account equity components mismatch")
        equity.append(value)
    returns=[b/a-1 for a,b in zip(equity,equity[1:])]
    peak=equity[0]
    drawdown=0.
    for value in equity:
        peak=max(peak,value)
        drawdown=max(drawdown,1-value/peak)
    if not isclose(drawdown,_num(replay["maximum_close_drawdown"],"drawdown",0,1),abs_tol=1e-8):
        raise ValueError("Drawdown mismatch")
    if not isclose(equity[-1]/equity[0]-1,_num(replay["net_marked_return"],"marked return",-1,1e9),abs_tol=1e-8):
        raise ValueError("Marked return mismatch")
    volatility=stdev(returns) if len(returns)>1 else 0.
    sharpe=mean(returns)/volatility*sqrt(252) if volatility>1e-12 else None
    groups=defaultdict(list)
    net=[]
    pnl=[]
    seen=set()
    date_set=set(days)
    for row in episodes:
        entry,end=map(_day,(row["entry_date"],row["exit_date"]))
        stock=row["stock_id"]
        if (not isinstance(stock,str) or not stock.isascii() or not stock.isdigit() or stock in ("1589","1808")
                or entry not in date_set or end not in date_set or entry>end or (stock,entry) in seen):
            raise ValueError("Invalid closed episode")
        seen.add((stock,entry))
        ret=_num(row["net_return"],"net return",-1,1000)
        money=_num(row["net_pnl"],"net pnl",-1e15,1e15)
        if (ret>0)!=(money>0) or (ret<0)!=(money<0):
            raise ValueError("Episode return and P&L signs disagree")
        net.append(ret)
        pnl.append(money)
        groups[entry].append(int(ret>0))
    diag=outcome_diagnostics(net) if net else None
    wins=fsum(x for x in pnl if x>0)
    losses=-fsum(x for x in pnl if x<0)
    pf=wins/losses if losses else None
    blocks={}
    ordered=[groups[d] for d in sorted(groups)]
    m=len(ordered)
    if len(net)>=500 and m>=100:
        cohort=[(sum(g),len(g)) for g in ordered]
        for size in (5,10,20):
            rng=random.Random(20261126+size)
            estimates=[]
            for _ in range(1000):
                w=n=used=0
                while used<m:
                    start=rng.randrange(m-size+1)
                    take=min(size,m-used)
                    for a,b in cohort[start:start+take]:
                        w+=a
                        n+=b
                    used+=take
                estimates.append(w/n)
            blocks[str(size)]=sorted(estimates)[49]
    lower=min([diag["net_win_rate"],*blocks.values()]) if blocks else None
    open_count=replay["open_position_count"]
    if type(open_count) is not int or open_count<0 or open_count!=len(path[-1]["holdings"]):
        raise ValueError("Invalid open-position count")
    gates={"closed_trades_500":len(net)>=500,
           "entry_dates_100":m>=100,
           "win_rate_80":bool(diag and diag["net_win_rate"]>=.8),
           "block_sensitivity_80":lower is not None and lower>=.8,
           "mean_return_payoff_2":bool(diag and diag["net_payoff_ratio"] is not None and diag["net_payoff_ratio"]>=2),
           "money_profit_factor_2":pf is not None and pf>=2,
           "sharpe_1_5":sharpe is not None and sharpe>=1.5,
           "close_drawdown_10":drawdown<=.1,
           "positive_marked_return":equity[-1]>equity[0],
           "no_open_episodes":open_count==0}
    metrics=dict(closed_trade_count=len(net),entry_date_count=m,
                 net_win_rate=diag["net_win_rate"] if diag else None,
                 mean_return_payoff_ratio=diag["net_payoff_ratio"] if diag else None,
                 money_profit_factor=pf,return_profit_factor=diag["profit_factor"] if diag else None,
                 net_marked_return=equity[-1]/equity[0]-1,maximum_close_drawdown=drawdown,
                 illustrative_annualized_sharpe=sharpe,return_sessions=len(returns),
                 entry_date_block_lower_5=blocks,sensitivity_lower_estimate=lower,
                 open_position_count=open_count)
    return {"metrics":metrics,"research_gates":gates,"all_numeric_gates_met":all(gates.values()),
            "ledger_sha256":_hash(dict(path=path,closed=episodes)),
            "sharpe_assumptions":"252 sessions/year; zero risk-free rate; sample volatility",
            "entry_date_blocks_not_verified_independent":True,"calendar_verified":False,
            "source_provenance_verified":False,"pristine_holdout_verified":False,
            "model_release":"BLOCKED","trading_approved":False}
