"""Research-only Taiwan-market scenario costs and liquidity sensitivity.

This intentionally avoids a universal "Taiwan trading tax" constant: stock,
ETF, day-trade and account fee treatments differ. Caller must *explicitly*
supply applicable fee, tax and slippage assumptions in basis points.
"""
from __future__ import annotations

from math import isfinite


def _nonnegative(value,name,upper):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not isfinite(value):
        raise ValueError(name+" requires finite numeric value")
    if not 0<=value<=upper:
        raise ValueError(name+" outside research bounds")
    return float(value)


def scenario(gross_return, *, entry_fee_bps, exit_fee_bps,
             sell_tax_bps, entry_slippage_bps, exit_slippage_bps,
             intended_notional_ntd=None, verified_daily_turnover_ntd=None,
             max_participation_fraction=.05):
    """Mark-to-market illustrative round-trip long-only *research* return.

    Price impact and fill probability cannot be deduced from the daily close.
    Slippage bps are user assumptions, and liquidity is only a static screen,
    not an execution guarantee. Percent returns are decimals, not 12 for 12%.
    """
    if isinstance(gross_return,bool) or not isinstance(gross_return,(float,int)) or not isfinite(gross_return) or gross_return<=-1 or gross_return>10:
        raise ValueError("gross_return must be decimal > -1 and <= 10")
    fee_in=_nonnegative(entry_fee_bps,"entry_fee_bps",2000)
    fee_out=_nonnegative(exit_fee_bps,"exit_fee_bps",2000)
    sell_tax=_nonnegative(sell_tax_bps,"sell_tax_bps",2000)
    slip_in=_nonnegative(entry_slippage_bps,"entry_slippage_bps",2000)
    slip_out=_nonnegative(exit_slippage_bps,"exit_slippage_bps",2000)
    if (fee_in+slip_in)>=10000 or (fee_out+slip_out+sell_tax)>=10000:
        raise ValueError("Cost assumptions eliminate transaction value")
    # Entry cost is paid on top of the buy price. Exit proceeds are reduced
    # by fees, tax and price slippage. Neither models minimum brokerage fees.
    net=(1+gross_return)*(1-(fee_out+sell_tax+slip_out)/10000)/(1+(fee_in+slip_in)/10000)-1
    liquidity="UNKNOWN"
    participation=None
    if (intended_notional_ntd is None)!=(verified_daily_turnover_ntd is None):
        raise ValueError("Liquidity screen needs both order notional and verified turnover")
    if intended_notional_ntd is not None:
        n=_nonnegative(intended_notional_ntd,"intended_notional_ntd",1e12)
        turnover=_nonnegative(verified_daily_turnover_ntd,"verified_daily_turnover_ntd",1e14)
        share=_nonnegative(max_participation_fraction,"max_participation_fraction",1)
        if turnover<=0 or n<=0 or share<=0:
            raise ValueError("Strictly positive notional, turnover and threshold required")
        participation=n/turnover
        liquidity="PASS_ASSUMED_LIMIT" if participation<=share else "EXCEEDS_ASSUMED_LIMIT"
    return {
        "net_return":round(net,10),
        "gross_return":round(gross_return,10),
        "cost_impact_percentage_points":round(100*(gross_return-net),6),
        "entry_cost_bps":fee_in+slip_in,
        "exit_cost_bps":fee_out+sell_tax+slip_out,
        "assumptions_provided_by_caller":True,
        "participation_ratio":round(participation,8) if participation is not None else None,
        "liquidity_screen":liquidity,
        "executable_fill_verified":False,
        "applicable_regulatory_tax_verified":False,
        "broking_minimum_fee_modelled":False,
        "orders_enabled":False
    }


def stress_test(gross_return, *, fee_bps, sell_tax_bps,
                slippage_bps_scenarios=(0,10,30,60),
                intended_notional_ntd=None, verified_daily_turnover_ntd=None):
    """Apply increasing assumed slippage symmetrically; never select best case."""
    if not isinstance(slippage_bps_scenarios,(list,tuple)) or not 1<=len(slippage_bps_scenarios)<=12:
        raise ValueError("Provide 1..12 bounded slippage cases")
    values=[_nonnegative(x,"slippage_bps",2000) for x in slippage_bps_scenarios]
    if len(set(values))!=len(values) or values!=sorted(values):
        raise ValueError("Scenarios must be sorted and distinct")
    out=[]
    for bps in values:
        out.append({
            "slippage_each_way_bps":bps,
            **scenario(gross_return,entry_fee_bps=fee_bps,exit_fee_bps=fee_bps,
                       sell_tax_bps=sell_tax_bps,
                       entry_slippage_bps=bps,exit_slippage_bps=bps,
                       intended_notional_ntd=intended_notional_ntd,
                       verified_daily_turnover_ntd=verified_daily_turnover_ntd),
        })
    return {"cases":out,"worst_assumed_net_return":min(c["net_return"] for c in out),
            "net_return_monotone_nonincreasing":all(
                out[i+1]["net_return"]<=out[i]["net_return"] for i in range(len(out)-1)),
            "sufficient_real_microstructure_data_for_executability":False,
            "research_only":True,"orders_enabled":False}
