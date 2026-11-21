"""Low-storage Taiwan OTC raw-market feature bridge for model research.

Uses REAL price bars and the existing proven technical/SMC calculators without
materializing a daily_adjusted_prices/daily_technicals/daily_smc row.

This produces RAW, UNADJUSTED, CAUSAL-ALGORITHM features, not the previously
released tw-factor-ridge-1 scores. Historical original source capture vintages,
ex-dividend total returns and survivorship still need independent proof.
"""
from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
import json
import math

from src.build_adjusted_prices import normalize_source_units
from src.technical_indicators import compute_indicators
from src.smc_indicators import compute_smc

VERSION="tw-raw-price-asof-bridge-1"
MAX_BARS=1600
MAX_SIGNALS=32
MIN_WARMUP_SESSIONS=240
FEATURE_NAMES=(
    "raw_ret5","raw_ret20","raw_ma20_gap","raw_ma55_gap",
    "raw_rsi14_fraction","raw_atr14_fraction",
    "raw_volume_vs_ma20","raw_smc_trend",
    "raw_smc_bos_bullish","raw_smc_bos_bearish",
    "raw_smc_choch_bullish","raw_smc_choch_bearish",
)
OFFICIAL_SOURCE_TAGS=frozenset({
    "TPEX_DATED_OTC_EW","TPEX_DAILY_CLOSE_OPENAPI",
    "TPEX_TRADING_STOCK","TPEX_TRADING_STOCK_NORMALIZED",
})
OFFICIAL_TWSE_SOURCE_TAGS=frozenset({
    "TWSE_MI_INDEX_ALLBUT0999","TWSE_STOCK_DAY",
})

def _day(v):
    if type(v) is date:
        return v
    if type(v) is str:
        return date.fromisoformat(v)
    raise ValueError("Actual source trading date must be YYYY-MM-DD or date")

def _finite(v,name,*,positive=False):
    if isinstance(v,bool) or v is None:
        raise ValueError("Invalid raw source "+name)
    try:
        x=float(v)
    except (TypeError,ValueError,OverflowError) as exc:
        raise ValueError("Invalid raw source "+name) from exc
    if not math.isfinite(x) or (positive and x<=0):
        raise ValueError("Invalid raw source "+name)
    return x

def validate_source(raw,*,stock_id,cutoff,market="tpex"):
    if market not in ("tpex","twse"):
        raise ValueError("Unknown official market for source factor audit")
    allowed_sources=(OFFICIAL_SOURCE_TAGS if market=="tpex"
                     else OFFICIAL_TWSE_SOURCE_TAGS)
    if not isinstance(stock_id,str) or not stock_id.isascii() or not (
        stock_id.isdigit() and 4<=len(stock_id)<=6) or stock_id=="1808":
        raise ValueError("Fixed real official stock code required")
    end=_day(cutoff)
    if not isinstance(raw,list) or not 1<=len(raw)<=MAX_BARS:
        raise ValueError("Bounded original official OHLCV required")
    prev=None
    observed=[]
    sources={}
    for p in raw:
        if not isinstance(p,dict) or p.get("market")!=market or p.get("stock_id")!=stock_id:
            raise ValueError("Source stock-market identity failed")
        day=_day(p.get("trade_date"))
        if day>end or prev is not None and day<=prev:
            raise ValueError("Future, duplicate or unsorted official price day")
        if p.get("source") not in allowed_sources:
            raise ValueError("Unverified original price provenance")
        op=_finite(p.get("open"),"open",positive=True)
        hi=_finite(p.get("high"),"high",positive=True)
        lo=_finite(p.get("low"),"low",positive=True)
        cl=_finite(p.get("close"),"close",positive=True)
        if not lo<=min(op,cl)<=max(op,cl)<=hi:
            raise ValueError("Impossible official OHLCV source high/low")
        if _finite(p.get("volume"),"volume")<0:
            raise ValueError("Negative real official volume")
        observed.append((day.isoformat(),str(p.get("source")),op,hi,lo,cl,
                         str(p.get("volume"))))
        sources[p["source"]]=sources.get(p["source"],0)+1
        prev=day
    return observed,sources

def build_research_features(raw,*,stock_id,cutoff,signal_dates,market="tpex"):
    """Build *only as-of available* technical/SMC vectors from raw prices.

    Features never use a future date: the caller must pass rows <= cutoff.
    Internally all technical and SMC calculations use current and previous
    raw bars; the 3-bar swing-right feature is exposed only when confirmed.
    """
    asof=_day(cutoff)
    observed,sources=validate_source(raw,stock_id=stock_id,cutoff=asof,market=market)
    if (not isinstance(signal_dates,(list,tuple)) or not 1<=len(signal_dates)<=MAX_SIGNALS):
        raise ValueError("Bounded real signal sessions required")
    days=[_day(x) for x in signal_dates]
    if len(days)!=len(set(days)) or any(x>asof for x in days):
        raise ValueError("Duplicate or future-dated research signal")
    normalized=normalize_source_units(raw,market)
    technical=compute_indicators(normalized)
    smc=compute_smc(normalized)
    if len(technical)!=len(raw) or len(smc)!=len(raw):
        raise RuntimeError("Validated source dates and feature rows do not reconcile")
    index={_day(p["trade_date"]):i for i,p in enumerate(raw)}
    features=[]
    rejected=[]
    for day in sorted(days):
        i=index.get(day)
        if i is None:
            rejected.append({"signal_date":day.isoformat(),
                             "reason":"not_a_real_saved_stock_trading_session"})
            continue
        if i+1<MIN_WARMUP_SESSIONS:
            rejected.append({"signal_date":day.isoformat(),
                             "reason":"insufficient_real_warmup_sessions"})
            continue
        close=_finite(raw[i]["close"],"signal_close",positive=True)
        t=technical[i];s=smc[i]
        if any(t[k] is None for k in ("ma20","ma55","rsi14","atr14","volume_ma20")):
            rejected.append({"signal_date":day.isoformat(),
                             "reason":"incomplete_real_asof_indicator_window"})
            continue
        normalized_vol=_finite(normalized[i].get("volume"),"normalized_volume")
        ma20=_finite(t["ma20"],"ma20",positive=True)
        ma55=_finite(t["ma55"],"ma55",positive=True)
        vma=_finite(t["volume_ma20"],"volume_ma20",positive=True)
        values=[
            close/_finite(raw[i-5]["close"],"lag5_close",positive=True)-1,
            close/_finite(raw[i-20]["close"],"lag20_close",positive=True)-1,
            close/ma20-1,close/ma55-1,
            _finite(t["rsi14"],"rsi14")/100,
            _finite(t["atr14"],"atr14")/close,
            normalized_vol/vma,
            _finite(s["trend_direction"],"smc_trend"),
            float(bool(s["bos_bullish"])),float(bool(s["bos_bearish"])),
            float(bool(s["choch_bullish"])),float(bool(s["choch_bearish"]))
        ]
        if not all(math.isfinite(x) for x in values):
            raise ValueError("Nonfinite source-based training feature")
        features.append({"market":market,"stock_id":stock_id,
                         "as_of_date":day.isoformat(),"signal_raw_close":close,
                         "feature_vector":[round(x,12) for x in values],
                         "source_session_index":i,
                         "label_or_forward_price_observed":False})
    fingerprint=sha256(json.dumps(observed,separators=(",",":"),sort_keys=True,
                                  allow_nan=False).encode()).hexdigest()
    return {
        "schema_version":1,"feature_version":VERSION,
        "stock_id":stock_id,"market":market,
        "requested_cutoff":asof.isoformat(),
        "raw_first_date":observed[0][0],"raw_last_date":observed[-1][0],
        "source_rows":len(raw),"original_source_tags":sources,
        "raw_source_fingerprint_sha256":fingerprint,
        "requested_signals":len(days),"included_signals":len(features),
        "excluded_signal_days":rejected,
        "feature_names":list(FEATURE_NAMES),"signals":features,
        "causal_raw_price_calculators_reused":True,
        "corporate_actions_not_applied_to_features":True,
        "source_capture_vintage_at_old_signals_independently_proven":False,
        "past_issuer_listing_and_delisting_universe_verified":False,
        "current_dividend_adjusted_total_return_labels_verified":False,
        "incompatible_with_existing_composite_score_ridge_feature_schema":True,
        "holdout_independently_verified":False,
        "research_use_only":True,"live_trading_approved":False,
        "line_signals_approved":False,
        "database_write_operations":0,
    }
