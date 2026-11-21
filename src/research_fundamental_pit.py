"""Point-in-time fundamental *research schema*, no external data collection.

A fiscal period end is NOT the disclosure date. The module requires an
offset-aware published_at and recorded_at for each revision, and an explicit
market-close as-of timestamp; do not silently forward-fill later restatements.
"""
from __future__ import annotations

from datetime import datetime,date
from zoneinfo import ZoneInfo
import math

TAIPEI=ZoneInfo("Asia/Taipei")
METRICS=("revenue_yoy_pct","eps_ttm_ntd","roe_pct",
         "operating_cash_flow_ttm_ntd","debt_to_equity_pct","pe_ratio")
PERCENT_FIELDS={"revenue_yoy_pct","roe_pct","debt_to_equity_pct"}


def _time(value):
    if isinstance(value,str):
        try:
            value=datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Exact timestamp with timezone required") from exc
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Exact timestamp with timezone required")
    return value.astimezone(TAIPEI)


def _day(value):
    if isinstance(value,date) and not isinstance(value,datetime):
        return value
    if isinstance(value,str):
        return date.fromisoformat(value)
    raise ValueError("Fiscal period YYYY-MM-DD required")


def _value(v):
    if isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v):
        raise ValueError("Finite numeric fundamental observation required")
    if abs(v)>1e15:
        raise ValueError("Unsupported extreme fundamental observation")
    return float(v)


def asof_fundamentals(observations, *, as_of_close, market="twse",
                      stock_id="2330", max_records=2000):
    """Return as-known-at-close observations; never infer official release time.

    If multiple publications share a fiscal period, only a revision recorded
    *before* the signal close is eligible. Different reporting periods must
    be represented explicitly and the latest eligible period wins.
    """
    signal=_time(as_of_close)
    if signal.hour!=13 or signal.minute!=30 or signal.second or signal.microsecond:
        raise ValueError("Pass Taiwan 13:30 market-close time as the signal cutoff")
    if market not in ("twse","tpex") or not isinstance(stock_id,str) or not stock_id.isascii() or not stock_id.isdigit():
        raise ValueError("Invalid market/symbol")
    if not isinstance(observations,list) or len(observations)>max_records:
        raise ValueError("Bounded observations list required")
    eligible={}
    excluded={"future_publication":0,"future_revision":0,"other_stock":0}
    fingerprints=set()
    for obs in observations:
        if not isinstance(obs,dict):
            raise ValueError("Invalid fundamental observation")
        obs_market,obs_stock=obs.get("market"),obs.get("stock_id")
        if obs_market not in ("twse","tpex") or not isinstance(obs_stock,str):
            raise ValueError("Missing symbol provenance")
        metric=obs.get("metric")
        if metric not in METRICS:
            raise ValueError("Unknown fundamental metric")
        period=_day(obs.get("period_end"))
        published=_time(obs.get("published_at"))
        recorded=_time(obs.get("recorded_at"))
        if published.date()<period or recorded<published:
            raise ValueError("Disclosure before financial period end or recording before publication")
        value=_value(obs.get("value"))
        if metric in PERCENT_FIELDS and abs(value)>10000:
            raise ValueError("Invalid percentage range")
        if metric=="debt_to_equity_pct" and value<0:
            raise ValueError("Negative debt-to-equity is not comparable for this research schema")
        ident=(obs_market,obs_stock,metric,period.isoformat(),published.isoformat(),recorded.isoformat())
        if ident in fingerprints:
            raise ValueError("Duplicate fundamental observation")
        fingerprints.add(ident)
        if obs_market!=market or obs_stock!=stock_id:
            excluded["other_stock"]+=1
            continue
        if published>signal:
            excluded["future_publication"]+=1
            continue
        if recorded>signal:
            excluded["future_revision"]+=1
            continue
        key=metric
        marker=(period,published,recorded)
        if key not in eligible or marker>eligible[key]["marker"]:
            eligible[key]={
                "marker":marker,"value":value,"period_end":period.isoformat(),
                "published_at":published.isoformat(),"recorded_at":recorded.isoformat(),
                "source":obs.get("source") or "UNVERIFIED_USER_SUPPLIED",
            }
    fields={}
    for name in METRICS:
        if name in eligible:
            fields[name]={k:v for k,v in eligible[name].items() if k!="marker"}
        else:
            fields[name]=None
    return {
        "schema_version":1,"market":market,"stock_id":stock_id,
        "signal_cutoff_taipei":signal.isoformat(),
        "fields":fields,
        "metric_coverage":round(sum(v is not None for v in fields.values())/len(METRICS),6),
        "excluded":excluded,
        "point_in_time_release_and_revision_cutoff_enforced":True,
        "data_sources_independently_verified":False,
        "all_fundamental_factors_applied_to_live_model":False,
        "investment_quality_or_future_return_predicted":False,
        "orders_enabled":False,
    }
