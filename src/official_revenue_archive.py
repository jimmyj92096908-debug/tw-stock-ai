"""Strict time-of-first-observation archive for official TWSE/TPEx revenue.

The exchange batch's 出表日期 is NOT each issuer's published_at. A snapshot
captured today must NEVER be backdated into last month's signal information.
Historical models may use a value only from the saved first_observed_at forward.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from zoneinfo import ZoneInfo

TAIPEI=ZoneInfo("Asia/Taipei")
SOURCES={
    "twse":"https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
    "tpex":"https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O",
}
MAX_ROWS=2500
KEYS=("公司代號","資料年月","出表日期","營業收入-當月營收")
MONTHLY_FIELD="營業收入-當月營收"
YOY_FIELD="營業收入-去年同月增減(%)"


def aware(value):
    if isinstance(value,str):
        value=datetime.fromisoformat(value)
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Real timezone-aware retrieval timestamp required")
    return value.astimezone(TAIPEI)


def roc_day(raw):
    text=str(raw)
    if not re.fullmatch(r"\d{7}",text):
        raise ValueError("Official ROC table date must be 7 digits")
    return date(int(text[:3])+1911,int(text[3:5]),int(text[5:7]))


def roc_period(raw):
    text=str(raw)
    if not re.fullmatch(r"\d{5}",text):
        raise ValueError("Official ROC revenue period must be 5 digits")
    year,month=int(text[:3])+1911,int(text[3:])
    start=date(year,month,1)
    if month==12:
        next_month=date(year+1,1,1)
    else:
        next_month=date(year,month+1,1)
    return next_month-timedelta(days=1)


def decimal_or_none(value,*,max_abs=Decimal("1000000000000000")):
    if value is None:
        return None
    if isinstance(value,bool):
        raise ValueError("Boolean cannot be a financial amount")
    token=str(value).strip().replace(",","")
    if token in ("","--","---","N/A","不適用"):
        return None
    try:
        v=Decimal(token)
    except InvalidOperation as e:
        raise ValueError("Unparseable official finance number") from e
    if not v.is_finite() or abs(v)>max_abs:
        raise ValueError("Unsupported finance number")
    return v


def parse_snapshot(market,source_rows,*,observed_at):
    if market not in SOURCES:
        raise ValueError("Unknown official exchange source")
    at=aware(observed_at)
    if not isinstance(source_rows,list) or not 1<=len(source_rows)<=MAX_ROWS:
        raise ValueError("Official JSON row cap 1..2500")
    records=[]
    seen=set()
    for raw in source_rows:
        if not isinstance(raw,dict) or any(k not in raw for k in KEYS):
            raise ValueError("Required original exchange columns missing")
        stock_id=str(raw["公司代號"]).strip()
        if not re.fullmatch(r"\d{4,6}",stock_id):
            # Official dataset can include other issuer types; do not invent ticker keys.
            continue
        period=roc_period(raw["資料年月"])
        table_day=roc_day(raw["出表日期"])
        if table_day<period or table_day>at.date():
            raise ValueError("Official table date outside known observation period")
        if period>at.date():
            raise ValueError("Source fiscal period is in the future")
        key=(market,stock_id,period.isoformat())
        if key in seen:
            raise ValueError("Duplicate official monthly issuer/period")
        seen.add(key)
        revenue=decimal_or_none(raw[MONTHLY_FIELD])
        if revenue is None:
            continue
        yoy=decimal_or_none(raw.get(YOY_FIELD),max_abs=Decimal("100000"))
        if yoy is not None and abs(yoy)>Decimal("10000"):
            # Extremely anomalous YoY data cannot be safely treated as a factor.
            yoy=None
        material={
            "market":market,"stock_id":stock_id,"period_end":period.isoformat(),
            "reported_revenue_thousands_ntd":str(revenue),
            "reported_yoy_pct":str(yoy) if yoy is not None else None,
            "official_table_date":table_day.isoformat(),
        }
        fingerprint=sha256(json.dumps(material,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
        records.append({
            **material,
            "first_observed_at":at.isoformat(),
            "source_url":SOURCES[market],
            "payload_sha256":fingerprint,
        })
    if not records:
        raise ValueError("Official source had no valid timestamped revenue data")
    return records


def asof_archive(observations,*,market,stock_id,signal_cutoff):
    """Return ONLY records first seen on/before the actual 13:30 signal close."""
    at=aware(signal_cutoff)
    if (at.hour,at.minute,at.second,at.microsecond)!=(13,30,0,0):
        raise ValueError("The as-of research cutoff is Taiwan 13:30")
    if market not in SOURCES or not re.fullmatch(r"\d{4,6}",stock_id):
        raise ValueError("Invalid known exchange/symbol")
    if not isinstance(observations,list) or len(observations)>500:
        raise ValueError("Bounded archive query required")
    accepted=[]
    for x in observations:
        if x.get("market")!=market or x.get("stock_id")!=stock_id:
            continue
        viewed=aware(x["first_observed_at"])
        period=date.fromisoformat(x["period_end"])
        official_day=date.fromisoformat(x["official_table_date"])
        if period>official_day or official_day>viewed.date():
            raise ValueError("Archived official date cannot exceed first actual observation")
        if viewed<=at:
            accepted.append(x)
    accepted.sort(key=lambda x:(x["period_end"],aware(x["first_observed_at"]),x["payload_sha256"]))
    best=accepted[-1] if accepted else None
    return {
        "market":market,"stock_id":stock_id,"as_of":at.isoformat(),
        "revenue":best,
        "metric_covered":best is not None,
        "publication_timestamp_known":False,
        "first_observation_after_initial_publication_possible":True,
        "usable_as_earlier_historical_information":False,
        "trading_approved":False,
    }
