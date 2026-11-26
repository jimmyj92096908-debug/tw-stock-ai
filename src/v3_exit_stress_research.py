"""Conservative offline OHLC exit stress replay for an existing long position.

Not an execution model: caller must supply independently verified eligibility,
raw prices, price limits and liquidity capacity. No inferred fills from volume.
No production integration, orders, corporate action or settlement handling.
"""
from __future__ import annotations

from src.v3_capital_risk_research import _num
from src.v3_probability_calibration import _day


def replay_exit(*, entry_date, entry_price, shares, sessions,
                stop_fraction=0.05, profit_fraction=0.10,
                trailing_fraction=0.05, commission=0.001425,
                sell_tax=0.003, slippage=0.001, lot_size=1000):
    """Replay an already held position from the session after entry.

    Stops and profit targets use raw prices; if both are touched, assume stop
    first. Trailing high-water mark uses prior sessions only. Once triggered,
    an unfilled stop or profit exit becomes a persistent liquidation request.
    Capacity is an external hypothetical per-session sell-share ceiling;
    unknown capacity, suspension or blocked sell flag imply no fill.
    """
    entry = _day(entry_date)
    price = _num(entry_price, "entry price", 0.01, 1e7)
    if type(lot_size) is not int or lot_size not in (1,1000):
        raise ValueError("Unsupported lot size")
    if type(shares) is not int or shares <= 0 or shares % lot_size:
        raise ValueError("Invalid shares")
    stop, profit, trail = (
        _num(stop_fraction,"stop",0.0001,0.99),
        _num(profit_fraction,"profit",0.0001,10),
        _num(trailing_fraction,"trail",0.0001,0.99))
    fee, tax, slip = (_num(v,"cost",0,0.1) for v in
                      (commission,sell_tax,slippage))
    if not isinstance(sessions,list) or not 1 <= len(sessions) <= 2000:
        raise ValueError("Require bounded sessions")
    remaining, high_water, previous = shares, price, entry
    pending, fills, events = None, [], []
    cost = price * shares * (1+fee)
    proceeds = 0.0
    last_close = price
    for row in sessions:
        day = _day(row["date"])
        if day <= previous:
            raise ValueError("Exit sessions must follow entry in strict order")
        previous = day
        if row.get("corporate_action_clear") is not True:
            raise ValueError("Corporate action not supported")
        op, hi, lo, close = (_num(row[k],k,0.01,1e7)
                             for k in ("open","high","low","close"))
        if not lo <= min(op,close) <= max(op,close) <= hi:
            raise ValueError("Invalid OHLC")
        last_close = close
        eligible = row.get("sell_eligible")
        if eligible is not None and type(eligible) is not bool:
            raise ValueError("Invalid sell eligibility")
        cap = row.get("sell_capacity_shares")
        if cap is not None and (type(cap) is not int or cap < 0):
            raise ValueError("Invalid sell capacity")
        if remaining == 0:
            continue
        level = max(price*(1-stop), high_water*(1-trail))
        target = price*(1+profit)
        if pending is not None:
            reference, reason = op, "PENDING_EXIT"
        elif op <= level:
            reference, reason = op, "GAP_STOP"
        elif lo <= level:
            reference, reason = level, "STOP_FIRST" if hi >= target else "STOP"
        elif op >= target:
            # An opening target touch is known before intraday lows, but
            # this pessimistic stress convention still prefers a stop.
            reference, reason = target, "PROFIT"
        elif hi >= target:
            reference, reason = target, "PROFIT"
        else:
            high_water = max(high_water, hi)
            continue
        if pending is None:
            pending = reason
        qty = min(remaining, (cap//lot_size)*lot_size) if eligible is True and cap is not None else 0
        if qty:
            # A hypothetical adverse fill bounded by the observed session low.
            # Does not establish actual quote, queue position or fillability.
            fill = max(lo, reference*(1-slip))
            net = qty*fill*(1-fee-tax)
            proceeds += net
            remaining -= qty
            fills.append({"date":day.isoformat(),"reason":reason,
                          "shares":qty,"fill":fill,"net_proceeds":net})
        events.append({"date":day.isoformat(),"reason":reason,
                       "filled_shares":qty,"remaining_shares":remaining})
        high_water = max(high_water,hi)
    return {"fills":fills,"events":events,"remaining_shares":remaining,
            "exit_pending":remaining>0 and pending is not None,
            "net_closed_return":proceeds/cost-1 if remaining==0 else None,
            "net_marked_return":(proceeds+remaining*last_close)/cost-1,
            "assumed_entry_cost":cost,"net_sale_proceeds":proceeds,
            "liquidity_provenance_verified":False,
            "intraday_sequence_verified":False,"corporate_actions_supported":False,
            "integrated_portfolio_ledger":False,
            "model_release":"BLOCKED","trading_approved":False}
