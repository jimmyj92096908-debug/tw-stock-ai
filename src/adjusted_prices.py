"""Apply verified corporate-action factors to historical OHLCV without mutating raw bars."""
from __future__ import annotations
from math import isfinite
from typing import Any, Iterable

def adjust_bars(rows: Iterable[dict[str, Any]], actions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    bars=sorted(list(rows), key=lambda r: str(r["trade_date"]))
    events=list(actions)
    previous=None
    for event in events:
        pf=float(event["price_factor"]); sf=float(event["share_factor"])
        if not isfinite(pf) or not isfinite(sf) or pf<=0 or sf<=0:
            raise ValueError("公司行動調整係數必須是有限正數")
    result=[]
    for bar in bars:
        d=str(bar["trade_date"])
        price_factor=1.0; share_factor=1.0
        for event in events:
            if str(event["ex_date"]) > d:
                price_factor *= float(event["price_factor"])
                share_factor *= float(event["share_factor"])
        item=dict(bar)
        for field in ("open","high","low","close"):
            value=bar.get(field)
            item[field]=None if value is None else float(value)*price_factor
        volume=bar.get("volume")
        item["volume"]=None if volume is None else float(volume)*share_factor
        item["price_adjustment_factor"]=price_factor
        item["share_adjustment_factor"]=share_factor
        item["adjustment_status"]="ADJUSTED" if price_factor != 1.0 or share_factor != 1.0 else "UNADJUSTED"
        if item["close"] is not None and previous is not None:
            item["price_change"]=item["close"]-previous
        else:
            item["price_change"]=None
        if item["close"] is not None:
            previous=item["close"]
        result.append(item)
    return result
