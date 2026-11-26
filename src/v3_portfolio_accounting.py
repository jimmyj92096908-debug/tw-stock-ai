"""Offline long-only V3 portfolio accounting prototype.

Caller supplies aligned raw-price bars and prior-close frozen target weights.
No data authentication, stop execution or live orders. Optional limited gross
cash dividends and immediate whole-share conversions; other actions blocked.
Assumes idealized opening fills with proportional costs and T+2 session settlement.
"""
from __future__ import annotations

from math import floor, fsum
from src.v3_corporate_action_ledger import opening_action_step
from src.v3_capital_risk_research import _num
from src.v3_probability_calibration import _day


def simulate_portfolio(sessions, *, starting_cash=1000000, lot_size=1000,
                       commission=0.001425, sell_tax=0.003, slippage=0.001,
                       corporate_action_mode=False):
    """Target maps are full desired account weights; absent maps mean no rebalance.

    Targets at close t can affect open t+1 only. Opening price is used for
    hypothetical sizing. Sell proceeds are unavailable to buy until T+2.
    Whole-lot buys, no borrowing or shorting. Unfilled residuals are not carried.
    Costs are illustrative and omit minimum commission and price-limit fills.
    """
    if type(corporate_action_mode) is not bool:
        raise ValueError("Invalid corporate action mode")
    # Opt-in requires explicit daily action lists and bar-level event markers.
    # First session must have no events; account starts entirely in cash.
    dividend_pending, applied_ids = [], []
    cash = _num(starting_cash, "starting cash", 1, 1e12)
    initial = cash
    if type(lot_size) is not int or lot_size not in (1, 1000):
        raise ValueError("Unsupported lot size")
    fee, tax, slip = (_num(x, "cost", 0, 0.1) for x in (commission, sell_tax, slippage))
    if not isinstance(sessions, list) or not 2 <= len(sessions) <= 2000:
        raise ValueError("Require bounded chronological sessions")
    holdings, episodes, pending_cash = {}, {}, []
    trades, closed, path = [], [], []
    universe = None
    previous, targets = None, None
    peak, max_dd = initial, 0.0
    for i, session in enumerate(sessions):
        day = _day(session["date"])
        if previous is not None and day <= previous:
            raise ValueError("Unordered sessions")
        prior_day, previous = previous, day
        bars = session["bars"]
        if not isinstance(bars, dict) or not 1 <= len(bars) <= 2000:
            raise ValueError("Missing or excessive bar universe")
        if universe is None:
            universe = set(bars)
        if set(bars) != universe:
            raise ValueError("Incomplete aligned bar universe")
        prices = {}
        action_stocks = set()
        actions = session.get("corporate_actions", [])
        if not isinstance(actions, list):
            raise ValueError("Expected corporate action list")
        if corporate_action_mode:
            if "corporate_actions" not in session or (i == 0 and actions):
                raise ValueError("Missing daily action list or first-session event")
            for action in actions:
                s = action["stock_id"]
                if s not in bars or action["market"] != bars[s]["market"]:
                    raise ValueError("Action does not match bar universe")
                action_stocks.add(s)
        elif actions:
            raise ValueError("Corporate action mode disabled")
        for stock, row in bars.items():
            if (not isinstance(stock, str) or not stock.isascii() or not stock.isdigit()
                    or stock == "1589" or row.get("currently_listed") is not True
                    or row.get("market") not in ("TWSE", "TPEx")):
                raise ValueError("Invalid or excluded instrument")
            if row.get("corporate_action_clear") is not (stock not in action_stocks):
                raise ValueError("Corporate action marker mismatch or unsupported event")
            prices[stock] = (_num(row["open"], "open", 0.01, 1e7),
                             _num(row["close"], "close", 0.01, 1e7))
        cash += fsum(v for due,v in pending_cash if due <= i)
        pending_cash = [(due,v) for due,v in pending_cash if due > i]
        dividend_balance = 0.0
        if corporate_action_mode and i > 0:
            result = opening_action_step(
                session_date=day.isoformat(), previous_session_date=prior_day.isoformat(),
                holdings=holdings, pending_dividends=dividend_pending,
                applied_event_ids=applied_ids, actions=actions)
            # Attribute gross entitlements to the episode held before ex-date,
            # even if that episode is closed before cash credit.
            for a in actions:
                s = a["stock_id"]
                if a["kind"] == "CASH_DIVIDEND" and holdings.get(s,0):
                    e = episodes[s]
                    e["gross_dividends"] = e.get("gross_dividends",0.0) + (
                        holdings[s]*float(a["cash_per_share"]))
            holdings = result["holdings"]
            if any(q % lot_size for q in holdings.values()):
                raise ValueError("Conversion requires unsupported odd-lot execution mode")
            dividend_pending = result["pending_dividends"]
            applied_ids = result["applied_event_ids"]
            cash += float(result["gross_cash_credited"])
            dividend_balance = float(result["gross_receivable_balance"])
        if targets is not None:
            equity = cash + dividend_balance + fsum(v for _,v in pending_cash) + fsum(
                qty*prices[s][0] for s,qty in holdings.items())
            desired = {s: floor(equity*targets.get(s,0)/
                         (prices[s][0]*(1+slip)*(1+fee)*lot_size))*lot_size
                       for s in universe}
            for s in sorted(holdings):
                qty = holdings[s] - desired[s]
                if qty <= 0:
                    continue
                fill = prices[s][0]*(1-slip)
                proceeds = qty*fill*(1-fee-tax)
                pending_cash.append((i+2,proceeds))
                holdings[s] -= qty
                episodes[s]["proceeds"] += proceeds
                trades.append({"date":day.isoformat(),"stock_id":s,"side":"SELL",
                               "shares":qty,"fill":fill,"cash_flow":proceeds})
                if not holdings[s]:
                    e = episodes.pop(s)
                    closed.append({"stock_id":s,"entry_date":e["entry_date"],
                                   "exit_date":day.isoformat(),
                                   "gross_dividends":e.get("gross_dividends",0.0),
                                   "net_pnl":e["proceeds"]+e.get("gross_dividends",0.0)-e["cost"],
                                   "net_return":(e["proceeds"]+e.get("gross_dividends",0.0))/e["cost"]-1})
            # Deterministic ticker order; not a ranked execution optimizer.
            for s in sorted(universe):
                unit = prices[s][0]*(1+slip)*(1+fee)
                qty = min(desired[s]-holdings.get(s,0), floor(max(0,cash)/(unit*lot_size))*lot_size)
                if qty <= 0:
                    continue
                cost = qty*unit
                cash -= cost
                holdings[s] = holdings.get(s,0)+qty
                e = episodes.setdefault(s,{"entry_date":day.isoformat(),"cost":0.0,"proceeds":0.0})
                e["cost"] += cost
                trades.append({"date":day.isoformat(),"stock_id":s,"side":"BUY",
                               "shares":qty,"fill":prices[s][0]*(1+slip),"cash_flow":-cost})
            holdings = {s:q for s,q in holdings.items() if q}
        receivable = fsum(v for _,v in pending_cash)
        marked = fsum(q*prices[s][1] for s,q in holdings.items())
        equity = cash+receivable+marked+dividend_balance
        peak = max(peak,equity)
        max_dd = max(max_dd,1-equity/peak)
        if cash < -1e-7:
            raise AssertionError("Negative cash")
        path.append({"date":day.isoformat(),"available_cash":cash,
                     "unsettled_sale_proceeds":receivable,"market_value":marked,
                     "gross_dividend_receivable":dividend_balance,
                     "equity":equity,"holdings":dict(holdings)})
        targets = session.get("close_targets")
        if targets is not None:
            if not isinstance(targets,dict) or not set(targets)<=universe:
                raise ValueError("Invalid target map")
            targets = {s:_num(w,"weight",0,0.1) for s,w in targets.items()}
            if fsum(targets.values())>0.8+1e-12:
                raise ValueError("Gross target exceeds research ceiling")
    return {"path":path,"fills":trades,"closed_position_episodes":closed,
            "open_position_count":len(holdings),"terminal_target_unexecuted":targets is not None,
            "net_marked_return":path[-1]["equity"]/initial-1,
            "maximum_close_drawdown":max_dd,
            "closed_episode_win_rate":sum(e["net_pnl"]>0 for e in closed)/len(closed) if closed else None,
            "calendar_provenance_verified":False,"corporate_actions_supported":corporate_action_mode,
            "corporate_action_scope":"GROSS_CASH_AND_IMMEDIATE_INTEGER_CONVERSION" if corporate_action_mode else "NONE",
            "dividend_taxes_supported":False,"corporate_action_provenance_verified":False,
            "stop_execution_supported":False,"liquidity_stress_verified":False,
            "target_provenance_verified":False,"model_release":"BLOCKED","trading_approved":False}
