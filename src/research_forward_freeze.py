"""Freeze FULL future research cohorts before their next tradable session.

Research-only: preserves the exact latest official-market-backed model feature
universe and rankings, but neither generates orders nor approves model alpha.
Post-facto reruns may NEVER overwrite a frozen date/model snapshot.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import math
from zoneinfo import ZoneInfo

import numpy as np

from src.trained_factor_model import (
    VERSION, FEATURE_NAMES, MIN_UNIVERSE, TOP_FRACTION,
    _model_order, _baseline_order, feature_vector, iso_day, number,
)

TAIPEI=ZoneInfo("Asia/Taipei")
MIN_FROZEN_UNIVERSE=50
MAX_FROZEN_UNIVERSE=2500
MAX_STALE_CALENDAR_DAYS=4


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,
                      separators=(",",":"),allow_nan=False)


def eligible_freeze_time(signal_date, *, as_of):
    if not isinstance(signal_date,date) or isinstance(signal_date,datetime):
        raise ValueError("Real date-only last signal session required")
    if not isinstance(as_of,datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("Actual timezone-aware capture time required")
    local=as_of.astimezone(TAIPEI)
    age=(local.date()-signal_date).days
    if not 0<=age<=MAX_STALE_CALENDAR_DAYS:
        raise ValueError("Cannot backdate or freeze an old signal date")
    # On the signal session only *after* the market closes.
    if age==0:
        if (local.hour,local.minute)<(14,0):
            raise ValueError("Signal day snapshot before market close")
    # Next-session price could already exist on weekdays after the opening.
    elif local.weekday()<5 and (local.hour,local.minute)>=(8,30):
        raise ValueError("Post-close frozen snapshot too late for next session")
    return local


def build_frozen_universe(rows,model,*,model_sha256,as_of,latest_market_date):
    if not isinstance(model,dict) or model.get("version")!=VERSION or        model.get("feature_names")!=list(FEATURE_NAMES):
        raise ValueError("Unrecognized frozen factor model and feature schema")
    weights=model.get("weights")
    if not isinstance(weights,list) or len(weights)!=len(FEATURE_NAMES) or        any(isinstance(w,bool) or number(w) is None for w in weights):
        raise ValueError("Invalid precommitted model coefficients")
    if not isinstance(model_sha256,str) or len(model_sha256)!=64 or        any(c not in "0123456789abcdef" for c in model_sha256):
        raise ValueError("Model artifact fingerprint required")
    if not isinstance(rows,list) or not MIN_FROZEN_UNIVERSE<=len(rows)<=MAX_FROZEN_UNIVERSE:
        raise ValueError("Too small, absent or unbounded full signal cohort")

    dates={iso_day(r.get("as_of_date")) for r in rows}
    if len(dates)!=1:
        raise ValueError("Mixed score as-of dates")
    signal_date=date.fromisoformat(next(iter(dates)))
    latest=date.fromisoformat(iso_day(latest_market_date))
    if latest!=signal_date:
        raise ValueError("Global latest true market close and score day differ")
    local=eligible_freeze_time(signal_date,as_of=as_of)
    if date.fromisoformat(model.get("trained_through","9999-12-31"))>=signal_date:
        raise ValueError("Frozen model includes or follows the prospective signal date")
    if model.get("may_send_trade_signals") is not False or model.get("research_only") is not True:
        raise ValueError("Model must remain frozen research-only")
    if model.get("production_release_approved") is not False:
        raise ValueError("Release flag may not be enabled")

    names=set()
    members=[]
    for row in rows:
        market,stock=str(row.get("market")),str(row.get("stock_id"))
        if market not in ("twse","tpex") or not stock.isascii() or not stock.isdigit()            or not 4<=len(stock)<=6 or stock=="1808":
            raise ValueError("Unexpected issuer in prospectively frozen cohort")
        key=(market,stock)
        if key in names:
            raise ValueError("Duplicate issuer in frozen full cohort")
        names.add(key)
        features=feature_vector(row)
        close=number(row.get("signal_close"))
        score=number(row.get("total_score"))
        if features is None or close is None or close<=0 or score is None:
            raise ValueError("Invalid scored feature or price in entire cohort")
        members.append({
            "market":market,"stock_id":stock,"features":features,
            "raw_score":float(score),"close":float(close),
        })
    if len(members)!=len(rows):
        raise AssertionError("Cannot remove any issuer based on future data")
    model_order=_model_order(members,weights)
    baseline_order=_baseline_order(members)
    baseline_rank={j:i+1 for i,j in enumerate(baseline_order)}
    model_rank={j:i+1 for i,j in enumerate(model_order)}
    ordered_features=np.stack([x["features"] for x in members])
    centered=ordered_features-ordered_features.mean(axis=0)
    estimates=centered@np.asarray(weights,dtype=np.float64)
    if not np.all(np.isfinite(estimates)):
        raise ValueError("Nonfinite model ranking score")
    # Fully freeze all roster members, not only today's apparent winners:
    # excludes selection-by-observed-forward-label lookahead.
    stored=[
        {
            "market":row["market"],"stock_id":row["stock_id"],
            "raw_composite_score":round(row["raw_score"],8),
            "signal_close":round(row["close"],8),
            "feature_vector":[round(float(x),12) for x in row["features"]],
            "relative_model_score":round(float(estimates[i]),12),
            "model_rank":model_rank[i],"baseline_rank":baseline_rank[i],
        }
        for i,row in enumerate(members)
    ]
    stored.sort(key=lambda r:(r["market"],r["stock_id"]))
    selected=max(1,math.ceil(len(stored)*TOP_FRACTION))
    core={
        "schema_version":1,
        "model_version":VERSION,
        "model_sha256":model_sha256,
        "signal_date":signal_date.isoformat(),
        "universe_count":len(stored),
        "selected_count":selected,
        "members":stored,
    }
    digest=sha256(canonical(core).encode("utf-8")).hexdigest()
    return {
        **core,"cohort_sha256":digest,
        "snapshot_prepared_at":local.isoformat(),
        "forward_entry_price_or_return_observed":False,
        "confirmed_corporate_action_asof_vintage":False,
        "eligible_for_model_release":False,
        "line_signal_delivery_approved":False,
        "live_trading_approved":False,
    }


def summary(frozen):
    """No per-ticker predictions in CI/logs or over LINE."""
    return {k:frozen[k] for k in (
        "model_version","signal_date","model_sha256","cohort_sha256",
        "universe_count","selected_count","forward_entry_price_or_return_observed",
        "eligible_for_model_release","line_signal_delivery_approved",
        "live_trading_approved",
    )}
