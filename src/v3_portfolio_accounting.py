"""Offline long-only V3 portfolio accounting prototype.

Caller supplies aligned raw-price bars and prior-close frozen target weights.
No data authentication or live orders. Optional OHLC exit stress simulation. Optional limited gross
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
                       corporate_action_mode=False, exit_stress_mode=False,
                       stop_fraction=0.05, profit_fraction=0.10, trailing_fraction=0.05,
                       close_allocator=None):
    """Target maps are full desired account weights; absent maps mean no rebalance.

    Targets at close t can affect open t+1 only. Opening price is used for
    hypothetical sizing. Sell proceeds are unavailable to buy until T+2.
    Whole-lot buys, no borrowing or shorting. Unfilled residuals are not carried.
    Costs are illustrative and omit minimum commission and price-limit fills.
    """
    if type(corporate_action_mode) is not bool:
        raise ValueError("Invalid corporate action mode")
    if type(exit_stress_mode) is not bool:
        raise ValueError("Invalid exit stress mode")
    stop = _num(stop_fraction,"stop fraction",0.0001,0.99)
    profit = _num(profit_fraction,"profit fraction",0.0001,10)
    trail = _num(trailing_fraction,"trailing fraction",0.0001,0.99)
    if close_allocator is not None and (not callable(close_allocator) or not exit_stress_mode):
        raise ValueError("Close allocator requires exit stress mode")
    # Incremental allocation is separate from full target rebalancing.
    # A frozen close-time dollar budget may only shrink at the next open.
    pending_incremental, allocation_log = None, []
    # Exit mode uses explicit scenario capacities, not verified execution.
    # No scale-ins to existing episodes; pending exit blocks new buys.
    # Opening gap exits and pending exits precede target rebalance.
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
        sell_capacity, buy_capacity, ranges = {}, {}, {}
        blocked_today = set()
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
            if exit_stress_mode:
                op, close = prices[stock]
                lo = _num(row["low"],"low",0.01,1e7)
                hi = _num(row["high"],"high",0.01,1e7)
                if not lo <= min(op,close) <= max(op,close) <= hi:
                    raise ValueError("Invalid OHLC")
                ranges[stock] = (lo,hi)
                for side, capacities in (("sell",sell_capacity),("buy",buy_capacity)):
                    flag = row.get(side+"_eligible")
                    cap = row.get(side+"_capacity_shares")
                    if flag is not None and type(flag) is not bool:
                        raise ValueError("Invalid execution eligibility")
                    if cap is not None and (type(cap) is not int or cap < 0):
                        raise ValueError("Invalid scenario capacity")
                    capacities[stock] = (cap//lot_size)*lot_size if flag is True and cap is not None else 0
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
                if exit_stress_mode and holdings.get(s,0):
                    e = episodes[s]
                    # Adjust actual price levels rather than recomputing
                    # percentage stops from an already reduced entry price.
                    for k in ("fixed_stop","profit_target","high_water","trailing_stop"):
                        if a["kind"] == "CASH_DIVIDEND":
                            e[k] -= float(a["cash_per_share"])
                        else:
                            e[k] *= a["old_shares"]/a["new_shares"]
                        if e[k] <= 0:
                            raise ValueError("Unsupported nonpositive adjusted exit level")
            holdings = result["holdings"]
            if any(q % lot_size for q in holdings.values()):
                raise ValueError("Conversion requires unsupported odd-lot execution mode")
            dividend_pending = result["pending_dividends"]
            applied_ids = result["applied_event_ids"]
            cash += float(result["gross_cash_credited"])
            dividend_balance = float(result["gross_receivable_balance"])
        def sell(s, qty, reference, reason):
            if exit_stress_mode:
                qty = min(qty,sell_capacity[s])
            if qty <= 0:
                return
            fill = reference*(1-slip)
            proceeds = qty*fill*(1-fee-tax)
            pending_cash.append((i+2,proceeds))
            holdings[s] -= qty
            if exit_stress_mode:
                sell_capacity[s] -= qty
            episodes[s]["proceeds"] += proceeds
            trades.append({"date":day.isoformat(),"stock_id":s,"side":"SELL",
                           "shares":qty,"fill":fill,"cash_flow":proceeds,"reason":reason})
            if not holdings[s]:
                e = episodes.pop(s)
                dividends = e.get("gross_dividends",0.0)
                closed.append({"stock_id":s,"entry_date":e["entry_date"],
                               "exit_date":day.isoformat(),"gross_dividends":dividends,
                               "net_pnl":e["proceeds"]+dividends-e["cost"],
                               "net_return":(e["proceeds"]+dividends)/e["cost"]-1})
                del holdings[s]

        if exit_stress_mode:
            for s in sorted(holdings):
                e = episodes[s]
                op = prices[s][0]
                reason = ("PENDING_EXIT" if e.get("pending_exit") else
                          "GAP_STOP" if op <= max(e["fixed_stop"],e["trailing_stop"]) else
                          "OPEN_PROFIT" if op >= e["profit_target"] else None)
                if reason:
                    e["pending_exit"] = True
                    blocked_today.add(s)
                    sell(s,holdings[s],op,reason)
        if pending_incremental is not None:
            frozen_equity, increments = pending_incremental
            open_equity = cash + dividend_balance + fsum(v for _,v in pending_cash) + fsum(
                qty*prices[s][0] for s,qty in holdings.items())
            open_gross = fsum(q*prices[s][0] for s,q in holdings.items())
            # No new buying above global gross ceiling, even after gaps.
            open_room = max(0.0,0.8*open_equity-open_gross)
            for s in sorted(increments):
                if s in blocked_today or s in holdings:
                    continue
                unit = prices[s][0]*(1+slip)*(1+fee)
                budget = min(increments[s]*min(frozen_equity,open_equity),
                             cash,open_room)
                qty = min(floor(max(0,budget)/(unit*lot_size))*lot_size,buy_capacity[s])
                if qty<=0:
                    continue
                cost = qty*unit
                cash -= cost
                open_room = max(0.0,open_room-cost)
                holdings[s] = qty
                entry = prices[s][0]*(1+slip)
                episodes[s] = dict(entry_date=day.isoformat(),cost=cost,proceeds=0.0,
                                   fixed_stop=entry*(1-stop),profit_target=entry*(1+profit),
                                   high_water=entry,trailing_stop=entry*(1-trail),pending_exit=False)
                trades.append({"date":day.isoformat(),"stock_id":s,"side":"BUY",
                               "shares":qty,"fill":entry,"cash_flow":-cost,
                               "reason":"FROZEN_INCREMENTAL_ALLOCATION"})
            pending_incremental = None
        if targets is not None:
            equity = cash + dividend_balance + fsum(v for _,v in pending_cash) + fsum(
                qty*prices[s][0] for s,qty in holdings.items())
            desired = {s: floor(equity*targets.get(s,0)/
                         (prices[s][0]*(1+slip)*(1+fee)*lot_size))*lot_size
                       for s in universe}
            for s in sorted(holdings):
                if s not in blocked_today:
                    sell(s,holdings[s]-desired[s],prices[s][0],"REBALANCE")
            # Deterministic ticker order; not a ranked execution optimizer.
            for s in sorted(universe):
                if exit_stress_mode and (s in blocked_today or s in holdings):
                    continue
                unit = prices[s][0]*(1+slip)*(1+fee)
                qty = min(desired[s]-holdings.get(s,0), floor(max(0,cash)/(unit*lot_size))*lot_size)
                if exit_stress_mode:
                    qty = min(qty,buy_capacity[s])
                if qty <= 0:
                    continue
                cost = qty*unit
                cash -= cost
                holdings[s] = holdings.get(s,0)+qty
                e = episodes.setdefault(s,{"entry_date":day.isoformat(),"cost":0.0,"proceeds":0.0})
                e["cost"] += cost
                if exit_stress_mode:
                    entry = prices[s][0]*(1+slip)
                    e.update(fixed_stop=entry*(1-stop),profit_target=entry*(1+profit),
                             high_water=entry,trailing_stop=entry*(1-trail),pending_exit=False)
                trades.append({"date":day.isoformat(),"stock_id":s,"side":"BUY",
                               "shares":qty,"fill":prices[s][0]*(1+slip),"cash_flow":-cost})
            holdings = {s:q for s,q in holdings.items() if q}
        if exit_stress_mode:
            for s in sorted(holdings):
                if s in blocked_today:
                    continue
                e = episodes[s]
                lo,hi = ranges[s]
                level = max(e["fixed_stop"],e["trailing_stop"])
                target = e["profit_target"]
                if lo <= level or hi >= target:
                    # Same-session dual touch is pessimistically stop first.
                    reason = ("STOP_FIRST" if hi >= target else "STOP") if lo <= level else "PROFIT"
                    reference = min(prices[s][0],level) if lo <= level else target
                    e["pending_exit"] = True
                    sell(s,holdings[s],reference,reason)
                if s in holdings:
                    e = episodes[s]
                    if hi > e["high_water"]:
                        # Increase the stop only by the new high-water increment.
                        # Preserves additive cash-dividend adjustment.
                        e["trailing_stop"] += (hi-e["high_water"])*(1-trail)
                        e["high_water"] = hi
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
                     "equity":equity,"holdings":dict(holdings),
                     "pending_exit_stocks":sorted(s for s in holdings if episodes[s].get("pending_exit"))})
        targets = session.get("close_targets")
        if close_allocator is not None:
            if targets is not None:
                raise ValueError("Cannot mix incremental allocator with full target maps")
            position_state = []
            for s,q in sorted(holdings.items()):
                close = prices[s][1]
                e = episodes[s]
                level = min(close,max(e["fixed_stop"],e["trailing_stop"]))
                estimated_exit = level*(1-slip)*(1-fee-tax)
                position_state.append({"stock_id":s,"market":bars[s]["market"],
                    "account_weight":q*close/equity if equity else 0.0,
                    "remaining_stop_risk_fraction":max(0.0,1-estimated_exit/close),
                    "pending_exit":bool(e.get("pending_exit"))})
            snapshot = {"date":day.isoformat(),"equity":equity,
                        "cash_available":cash/equity if equity else 0.0,
                        "drawdown":1-equity/peak,"positions":position_state}
            proposal = close_allocator(snapshot)
            if not isinstance(proposal,dict) or not set(proposal)<=universe:
                raise ValueError("Invalid incremental proposal")
            proposal = {s:_num(w,"incremental weight",0,0.1) for s,w in proposal.items()}
            gross = fsum(x["account_weight"] for x in position_state)
            if (set(proposal)&set(holdings)
                    or fsum(proposal.values())>min(snapshot["cash_available"],max(0.0,0.8-gross))+1e-10
                    or (any(x["pending_exit"] for x in position_state) and any(proposal.values()))):
                raise ValueError("Incremental proposal exceeds close-state limits")
            pending_incremental = (equity,proposal) if proposal else None
            allocation_log.append({"date":day.isoformat(),"weights":dict(proposal)})
        if targets is not None:
            if not isinstance(targets,dict) or not set(targets)<=universe:
                raise ValueError("Invalid target map")
            targets = {s:_num(w,"weight",0,0.1) for s,w in targets.items()}
            if fsum(targets.values())>0.8+1e-12:
                raise ValueError("Gross target exceeds research ceiling")
    return {"path":path,"fills":trades,"closed_position_episodes":closed,
            "open_position_count":len(holdings),"terminal_target_unexecuted":targets is not None or pending_incremental is not None,
            "incremental_allocation_log":allocation_log,
            "incremental_allocator_integrated":close_allocator is not None,
            "net_marked_return":path[-1]["equity"]/initial-1,
            "maximum_close_drawdown":max_dd,
            "closed_episode_win_rate":sum(e["net_pnl"]>0 for e in closed)/len(closed) if closed else None,
            "calendar_provenance_verified":False,"corporate_actions_supported":corporate_action_mode,
            "corporate_action_scope":"GROSS_CASH_AND_IMMEDIATE_INTEGER_CONVERSION" if corporate_action_mode else "NONE",
            "dividend_taxes_supported":False,"corporate_action_provenance_verified":False,
            "stop_execution_supported":exit_stress_mode,"liquidity_stress_verified":False,
            "exit_scenario_capacity_verified":False,"intraday_sequence_verified":False,
            "target_provenance_verified":False,"model_release":"BLOCKED","trading_approved":False}
