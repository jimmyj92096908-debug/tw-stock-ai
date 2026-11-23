"""TWSE monthly stock source dates vs immutable owner 30 long 2022 gaps.

One free public TWSE STOCK_DAY request per unique issuer/month. The program
never exports a price, inserts K bars, makes Neon connections, touches LINE,
or mislabels absent STOCK_DAY rows as an official suspension or price error.
"""
from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from urllib.parse import parse_qs, urlparse

from scripts.twse_2021_22_traded_240_warmup_readonly import _private_file
from scripts.twse_2022_aes_neon_eligible_density_readonly import SCOPE as PARENT_SCOPE

ENDPOINT="https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
SCOPE="OWNER_TWSE_2022_LONG_GAPS_OFFICIAL_STOCK_DAY_MONTHLY_SOURCE_REVIEW"
MAX_QUERY_CALLS=90
MAX_RESPONSE_BYTES=2_000_000
MAX_INPUT_BYTES=150_000
MAX_OUTPUT_BYTES=180_000
EXPECTED={"runs":30,"stocks":116,"pairs":804,"all_runs":526}


def _stock_months(first,last):
    y,m=first.year,first.month
    out=[]
    while (y,m)<=(last.year,last.month):
        out.append(f"{y:04d}-{m:02d}")
        if m==12:
            y,m=y+1,1
        else:
            m+=1
    return out


def validate_owner_30_queue(receipt):
    """Fail closed against the actual PR238 frozen success scope."""
    if (not isinstance(receipt,dict) or
            receipt.get("schema_version")!=1 or
            receipt.get("scope")!=PARENT_SCOPE or
            receipt.get("year")!=2022 or
            receipt.get("official_current_listed_eligible_twse_issuers")!=1092 or
            receipt.get("aes_plus_neon_unique_observed_source_dates")!=246 or
            receipt.get("aes_neon_current_listed_stocks_with_all_246_source_dates")!=825 or
            receipt.get("model_release")!="BLOCKED" or
            receipt.get("production_neon_writes")!=0 or
            receipt.get("line_messages_sent")!=0):
        raise ValueError("Original PR238 owner authenticated source proof missing")
    queue=receipt.get("owner_private_all_30_long_source_absence_runs_official_check_queue")
    if (not isinstance(queue,dict) or
            queue.get("schema_version")!=1 or
            queue.get("underlying_116_source_absence_stocks")!=EXPECTED["stocks"] or
            queue.get("underlying_all_absent_stock_source_day_pairs")!=EXPECTED["pairs"] or
            queue.get("underlying_all_absent_source_day_runs")!=EXPECTED["all_runs"] or
            queue.get("at_least_six_unobserved_source_day_run_count")!=EXPECTED["runs"] or
            queue.get("all_30_long_source_absence_runs_recovered_from_source") is not True or
            queue.get("official_halt_or_resumption_not_checked_by_this_offline_step") is not True or
            queue.get("zero_stock_price_imputation") is not True or
            queue.get("model_release")!="BLOCKED" or
            queue.get("production_neon_writes")!=0 or
            queue.get("line_messages_sent")!=0):
        raise ValueError("Owner 30 long source interval proof drifted")
    rows=queue.get("owner_private_long_run_official_halt_check_queue")
    if not isinstance(rows,list) or len(rows)!=30:
        raise ValueError("Exactly 30 original source gap spans required")
    unique=set()
    required={}
    for item in rows:
        if not isinstance(item,dict):
            raise ValueError("Invalid owner source gap interval")
        sid=item.get("stock_id")
        if (not isinstance(sid,str) or not re.fullmatch(r"\d{4}",sid)
                or sid=="1589"):
            raise ValueError("Only current listed four digit 2022 stock IDs allowed")
        try:
            first=date.fromisoformat(item["first_unobserved_source_day"])
            last=date.fromisoformat(item["last_unobserved_source_day"])
        except (ValueError,TypeError,KeyError) as exc:
            raise ValueError("Invalid authenticated source gap date") from exc
        length=item.get("unobserved_consecutive_source_days")
        if (type(length) is not int or not 6<=length<=246
                or first.year!=2022 or last.year!=2022
                or first>last or (last-first).days+1<length
                or item.get("confirmed_official_halt_for_these_dates") is not False
                or item.get("confirmed_missing_price_repair_obligation") is not False):
            raise ValueError("Long gap source day count or provenance invalid")
        key=(sid,first,last)
        if key in unique:
            raise ValueError("Duplicate long source interval")
        unique.add(key)
        for m in _stock_months(first,last):
            required[(sid,m)]=None
    if len(required)>MAX_QUERY_CALLS:
        raise ValueError("Official free source request budget exceeded")
    return rows, sorted(required)


def _parse_roc_date(value,requested_month):
    if not isinstance(value,str):
        raise ValueError("Nontext official 2022 trading date")
    match=re.fullmatch(r"\s*(\d{2,3})/(\d{2})/(\d{2})\s*",value)
    if not match:
        raise ValueError("Unexpected official ROC date format")
    try:
        day=date(1911+int(match.group(1)),int(match.group(2)),int(match.group(3)))
    except ValueError as exc:
        raise ValueError("Impossible official monthly trading date") from exc
    if day.strftime("%Y-%m")!=requested_month:
        raise ValueError("Wrong month in official 2022 stock-day monthly response")
    return day


def _decimal(value):
    if not isinstance(value,str) or len(value)>32:
        return None
    if not re.fullmatch(r"[\d,]+(?:\.\d+)?",value.strip()):
        return None
    try:
        v=Decimal(value.strip().replace(",",""))
    except InvalidOperation:
        return None
    return v if v.is_finite() else None


def fetch_twse_stock_month(stock,month,*,get=None):
    """Read official monthly source dates only; never output raw price/volume."""
    if (not isinstance(stock,str) or not re.fullmatch(r"\d{4}",stock)
            or stock=="1589" or not re.fullmatch(r"2022-(0[1-9]|1[012])",month)):
        raise ValueError("Invalid bound official 2022 stock/month")
    if get is None:
        import requests
        get=requests.get
    params={"response":"json","date":month.replace("-","")+"01","stockNo":stock}
    r=get(ENDPOINT,params=params,headers={
        "Accept":"application/json",
        "User-Agent":"tw-stock-ai-free-owner-only-2022-original-stock-day-date-review",
    },timeout=(8,35),allow_redirects=False)
    r.raise_for_status()
    parsed=urlparse(r.url)
    got=parse_qs(parsed.query)
    if (r.status_code!=200 or parsed.scheme!="https" or
            parsed.hostname!="www.twse.com.tw" or
            parsed.path!="/rwd/zh/afterTrading/STOCK_DAY" or
            got!={k:[v] for k,v in params.items()}):
        raise ValueError("Official stock-day monthly response not exact TWSE HTTPS source")
    raw=r.content
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_RESPONSE_BYTES:
        raise ValueError("Official monthly source response exceeds limits")
    body=r.json()
    if not isinstance(body,dict):
        raise ValueError("Official source JSON is not an object")
    digest=sha256(raw).hexdigest()
    status=body.get("stat")
    if status!="OK":
        # API may return no-data for an issuer that never traded that
        # month. Not proof of formal halt or missing price.
        if not isinstance(status,str) or len(status)>150:
            raise ValueError("Unrecognized official stock-day status")
        return {"stock_id":stock,"month":month,
                "official_response_sha256":digest,
                "official_response_category":"UNVERIFIED_NO_DATA_RESPONSE",
                "official_valid_source_dates":[],
                "official_nonpositive_or_unparseable_close_dates":[],
                "official_response_not_a_halt_certificate":True}
    title=body.get("title")
    fields=body.get("fields")
    rows=body.get("data")
    if (not isinstance(title,str) or
            not re.search(r"(?<!\d)"+re.escape(stock)+r"(?!\d)",title)
            or not isinstance(fields,list) or len(fields)<7
            or fields[0]!="日期" or "成交股數" not in fields[1]
            or fields[6]!="收盤價" or
            not isinstance(rows,list) or not 1<=len(rows)<=31):
        raise ValueError("Official stock-month result lacks requested issuer or expected fields")
    valid=[]
    uncertain=[]
    seen=set()
    for rec in rows:
        if not isinstance(rec,list) or len(rec)<7:
            raise ValueError("Malformed official source stock date price record")
        day=_parse_roc_date(rec[0],month)
        if day in seen:
            raise ValueError("Duplicated official stock/month trading date")
        seen.add(day)
        volume=_decimal(rec[1])
        close=_decimal(rec[6])
        if volume is not None and volume>=0 and close is not None and close>0:
            valid.append(day.isoformat())
        else:
            uncertain.append(day.isoformat())
    return {
        "stock_id":stock,"month":month,
        "official_response_sha256":digest,
        "official_response_category":"OFFICIAL_MONTH_RETURNED_DATED_ROWS",
        "official_valid_source_dates":sorted(valid),
        "official_nonpositive_or_unparseable_close_dates":sorted(uncertain),
        "official_response_not_a_halt_certificate":True,
    }


def reconcile_official_30(receipt, monthly):
    rows,requests=validate_owner_30_queue(receipt)
    if (not isinstance(monthly,dict) or set(monthly)!=set(requests)):
        raise ValueError("Official issuer-month source proof incomplete")
    validated={}
    for key,rec in monthly.items():
        sid,month=key
        if (not isinstance(rec,dict)
                or rec.get("stock_id")!=sid or rec.get("month")!=month
                or not re.fullmatch(r"[0-9a-f]{64}",str(rec.get("official_response_sha256","")))
                or rec.get("official_response_not_a_halt_certificate") is not True
                or rec.get("official_response_category") not in (
                    "OFFICIAL_MONTH_RETURNED_DATED_ROWS",
                    "UNVERIFIED_NO_DATA_RESPONSE")):
            raise ValueError("Unverified TWSE 2022 issuer-month source evidence")
        clean={}
        for field in ("official_valid_source_dates",
                      "official_nonpositive_or_unparseable_close_dates"):
            values=rec.get(field)
            if not isinstance(values,list) or len(values)>31 or len(values)!=len(set(values)):
                raise ValueError("Official month source has inconsistent date keys")
            date_values=set()
            for value in values:
                try:
                    day=date.fromisoformat(value)
                except (ValueError,TypeError) as exc:
                    raise ValueError("Invalid official source market observation date") from exc
                if day.strftime("%Y-%m")!=month:
                    raise ValueError("Official result date outside queried month")
                date_values.add(day)
            clean[field]=date_values
        if clean["official_valid_source_dates"] & clean[
                "official_nonpositive_or_unparseable_close_dates"]:
            raise ValueError("One official stock date cannot be valid and invalid")
        if (rec["official_response_category"]=="UNVERIFIED_NO_DATA_RESPONSE"
                and any(clean.values())):
            raise ValueError("Official no-data source cannot contain trading rows")
        validated[key]=(rec,clean)
    decisions={
        "at_least_one_official_valid_source_row_in_gap_window":0,
        "official_rows_but_unverified_close_in_gap_window":0,
        "no_official_rows_in_gap_window_not_proof_of_halt":0,
        "official_month_no_data_response_cannot_classify":0,
    }
    outcomes=[]
    for item in rows:
        sid=item["stock_id"]
        start=date.fromisoformat(item["first_unobserved_source_day"])
        end=date.fromisoformat(item["last_unobserved_source_day"])
        evidence=[validated[(sid,m)] for m in _stock_months(start,end)]
        valid=sorted(set().union(*(
            {d for d in clean["official_valid_source_dates"] if start<=d<=end}
            for _,clean in evidence)))
        uncertain=sorted(set().union(*(
            {d for d in clean["official_nonpositive_or_unparseable_close_dates"]
             if start<=d<=end}
            for _,clean in evidence)))
        no_data=any(r["official_response_category"]==
                    "UNVERIFIED_NO_DATA_RESPONSE" for r,_ in evidence)
        if no_data:
            bucket="official_month_no_data_response_cannot_classify"
        elif valid:
            bucket="at_least_one_official_valid_source_row_in_gap_window"
        elif uncertain:
            bucket="official_rows_but_unverified_close_in_gap_window"
        else:
            bucket="no_official_rows_in_gap_window_not_proof_of_halt"
        decisions[bucket]+=1
        outcomes.append({
            "stock_id":sid,
            "first_unobserved_source_day":start.isoformat(),
            "last_unobserved_source_day":end.isoformat(),
            "unobserved_consecutive_source_days":item[
                "unobserved_consecutive_source_days"],
            "official_valid_source_dates_found_inside_window":[
                d.isoformat() for d in valid],
            "official_unverified_close_dates_inside_window":[
                d.isoformat() for d in uncertain],
            "official_source_month_provenance":[{
                "month":r["month"],
                "official_response_category":r["official_response_category"],
                "official_response_sha256":r["official_response_sha256"],
            } for r,_ in evidence],
            "observation_classification":bucket,
            "confirmed_formal_halt":False,
            "confirmed_data_fetch_gap_requiring_neon_backfill":False,
        })
    if sum(decisions.values())!=30:
        raise RuntimeError("Official source month/classifier did not reconcile 30 runs")
    return {
        "schema_version":1,
        "scope":SCOPE,
        "prior_authenticated_2022_30_long_source_gap_count":30,
        "prior_authenticated_2022_116_internal_absence_stock_count":116,
        "prior_authenticated_2022_all_804_unobserved_stock_source_dates":804,
        "official_unique_issuer_month_requests":len(requests),
        "official_months_with_dated_rows":sum(
            r["official_response_category"]=="OFFICIAL_MONTH_RETURNED_DATED_ROWS"
            for r,_ in validated.values()),
        "official_months_with_unverified_no_data_response":sum(
            r["official_response_category"]=="UNVERIFIED_NO_DATA_RESPONSE"
            for r,_ in validated.values()),
        "classification_counts":decisions,
        "owner_private_official_monthly_date_check_results":outcomes,
        "official_source_page":"https://www.twse.com.tw/zh/trading/historical/stock-day.html",
        "source_price_values_not_exported":True,
        "each_official_source_row_not_necessarily_fully_validated_ohlcv":True,
        "source_row_absence_does_not_certify_suspension":True,
        "historical_company_eligibility_and_board_events_not_full_pit":True,
        "no_automatic_price_gap_filling_or_deleting":True,
        "official_halt_or_resumption_status_finalized":False,
        "production_neon_writes":0,
        "line_messages_sent":0,
        "paid_service_used":False,
        "model_release":"BLOCKED",
    }


def main():
    p=argparse.ArgumentParser(
        description="TWSE official monthly source-date check for immutable owner-private 30 longest 2022 source gaps")
    p.add_argument("--prior-238-report",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args()
    try:
        source=_private_file(a.prior_238_report,should_exist=True)
        out=_private_file(a.out,should_exist=False)
        if source==out or source.stat().st_size>MAX_INPUT_BYTES:
            raise ValueError("Original owner report missing or oversized")
        receipt=json.loads(source.read_text(encoding="utf-8"))
        _rows,required=validate_owner_30_queue(receipt)
        proofs={}
        for sid,month in required:
            proofs[(sid,month)]=fetch_twse_stock_month(sid,month)
        report=reconcile_official_30(receipt,proofs)
        payload=json.dumps(report,ensure_ascii=False,indent=2,
                           allow_nan=False)+"\n"
        if len(payload.encode("utf-8"))>MAX_OUTPUT_BYTES:
            raise ValueError("Owner official evidence report exceeds output limit")
        with out.open("x",encoding="utf-8") as fp:
            fp.write(payload)
        print(json.dumps({
            "status":"TWSE_2022_30_GAPS_OFFICIAL_STOCK_DAY_MONTHLY_OBSERVATION_PASS",
            "official_issuer_month_requests":len(proofs),
            "classification_counts":report["classification_counts"],
            "verified_halt_or_price_repair_decisions":0,
            "neon_writes":0,
            "line_messages_sent":0,
            "model_release":"BLOCKED",
        },ensure_ascii=False))
    except Exception:
        raise SystemExit(
            "2022 30 gap official monthly source study FAILED; no changes to Neon, "
            "LINE, prices or historical private receipts, and no secrets printed"
        ) from None


if __name__=="__main__":
    main()
