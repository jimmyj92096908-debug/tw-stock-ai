"""Owner PR239: independently cross-check two 2022 unpriced source windows.

Reads an immutable owner-private summary of TWSE STOCK_DAY observation dates.
For exact 2022 dates where STOCK_DAY has a row but no parseable positive
close, fetch TWSE daily all-stock MI_INDEX from the free official site.
A positive source close is NOT permission to impute, write or trade.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from hashlib import sha256
import json
import re
from urllib.parse import parse_qs, urlparse

from scripts.twse_2021_22_traded_240_warmup_readonly import _private_file
from scripts.twse_2022_30_gap_official_stock_day_monthly_readonly import (
    SCOPE as PREVIOUS_SCOPE, _decimal,
)

SCOPE="OWNER_TWSE_2022_TWO_UNPRICED_GAP_WINDOWS_MI_INDEX_DAY_CHECK"
URL="https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
MAX_SOURCE_REPORT_BYTES=180_000
MAX_OUTPUT_BYTES=36000
MAX_HTTP_DAY_REQUESTS=30
MAX_HTTP_RESPONSE_BYTES=12_000_000
EXPECTED_CLASSES={
    "at_least_one_official_valid_source_row_in_gap_window":0,
    "official_rows_but_unverified_close_in_gap_window":2,
    "no_official_rows_in_gap_window_not_proof_of_halt":28,
    "official_month_no_data_response_cannot_classify":0,
}


def _read_date(raw):
    if not isinstance(raw,str):
        raise ValueError("Missing official previous source date")
    try:
        d=date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("Invalid previous official 2022 source date") from exc
    if d.year!=2022 or d.weekday()>=5:
        raise ValueError("Outside actual weekday 2022 research window")
    return d


def validate_prior_owner_uncertain_monthly_report(prior):
    """Only use exact two unresolved source windows from user PR239 success."""
    if (not isinstance(prior,dict)
            or prior.get("schema_version")!=1
            or prior.get("scope")!=PREVIOUS_SCOPE
            or prior.get("prior_authenticated_2022_30_long_source_gap_count")!=30
            or prior.get("prior_authenticated_2022_116_internal_absence_stock_count")!=116
            or prior.get("prior_authenticated_2022_all_804_unobserved_stock_source_dates")!=804
            or prior.get("official_unique_issuer_month_requests")!=40
            or prior.get("classification_counts")!=EXPECTED_CLASSES
            or prior.get("model_release")!="BLOCKED"
            or prior.get("production_neon_writes")!=0
            or prior.get("line_messages_sent")!=0
            or prior.get("no_automatic_price_gap_filling_or_deleting") is not True
            or prior.get("source_row_absence_does_not_certify_suspension") is not True):
        raise ValueError("Unverified owner PR239 2022 30-gap source audit")
    rows=prior.get("owner_private_official_monthly_date_check_results")
    if not isinstance(rows,list) or len(rows)!=30:
        raise ValueError("30 immutable official stock source gap classifications required")
    actual_count=Counter()
    all_intervals=set()
    uncertain=[]
    dates=set()
    for row in rows:
        if not isinstance(row,dict):
            raise ValueError("Malformed previous source gap row")
        sid=row.get("stock_id")
        if not isinstance(sid,str) or not re.fullmatch(r"\d{4}",sid) or sid=="1589":
            raise ValueError("Unlisted 1589 or invalid owner current listed issuer")
        first=_read_date(row.get("first_unobserved_source_day"))
        last=_read_date(row.get("last_unobserved_source_day"))
        if first>last:
            raise ValueError("Impossible owner gap time window")
        key=(sid,first,last)
        if key in all_intervals:
            raise ValueError("Duplicate owner 30 source gap interval")
        all_intervals.add(key)
        classification=row.get("observation_classification")
        if classification not in EXPECTED_CLASSES:
            raise ValueError("Unknown prior official source-date classification")
        actual_count[classification]+=1
        sources=row.get("official_source_month_provenance")
        if not isinstance(sources,list) or not 1<=len(sources)<=3:
            raise ValueError("Unverified old official monthly source provenance")
        for source in sources:
            if (not isinstance(source,dict)
                    or not re.fullmatch(r"2022-(0[1-9]|1[012])",
                                        str(source.get("month")))
                    or not re.fullmatch(r"[0-9a-f]{64}",
                                        str(source.get("official_response_sha256","")))):
                raise ValueError("Corrupt previous official monthly source digest")
        valid=row.get("official_valid_source_dates_found_inside_window")
        unpriced=row.get("official_unverified_close_dates_inside_window")
        if (not isinstance(valid,list) or not isinstance(unpriced,list)
                or len(set(valid))!=len(valid)
                or len(set(unpriced))!=len(unpriced)
                or len(valid)>31 or len(unpriced)>31
                or bool(set(valid)&set(unpriced))):
            raise ValueError("Ambiguous previous original source date sets")
        for item in valid+unpriced:
            d=_read_date(item)
            if not first<=d<=last:
                raise ValueError("Original official date outside owner gap interval")
        if classification=="official_rows_but_unverified_close_in_gap_window":
            if valid or not unpriced:
                raise ValueError("Expected only unpriced original monthly source rows")
            for value in unpriced:
                dates.add(_read_date(value))
                uncertain.append((sid,_read_date(value)))
        elif classification=="no_official_rows_in_gap_window_not_proof_of_halt":
            if valid or unpriced:
                raise ValueError("Prior official no-row classification fabricated")
        elif classification=="at_least_one_official_valid_source_row_in_gap_window":
            if not valid:
                raise ValueError("Prior valid original monthly observation missing")
        if (row.get("confirmed_formal_halt") is not False or
                row.get("confirmed_data_fetch_gap_requiring_neon_backfill") is not False):
            raise ValueError("Uncertified halt or fill permission in prior report")
    if dict(actual_count)!={
        k:v for k,v in EXPECTED_CLASSES.items() if v
    } or not 1<=len(dates)<=MAX_HTTP_DAY_REQUESTS:
        raise ValueError("Prior 2 unpriced windows/date count drifted")
    return sorted(set(uncertain)),sorted(dates)


def fetch_official_all_stock_source_day(day,*,get=None):
    if type(day) is not date or day.year!=2022 or day.weekday()>=5:
        raise ValueError("Only expected original 2022 market weekday allowed")
    if get is None:
        import requests
        get=requests.get
    params={"response":"json","date":day.strftime("%Y%m%d"),
            "type":"ALLBUT0999"}
    response=get(URL,params=params,timeout=(8,35),allow_redirects=False,
                 headers={
                     "Accept":"application/json",
                     "User-Agent":"tw-stock-ai-free-twse-2022-2-unpriced-multi-source-study",
                 })
    response.raise_for_status()
    u=urlparse(response.url)
    if (response.status_code!=200 or u.scheme!="https" or
            u.hostname!="www.twse.com.tw" or u.path!="/rwd/zh/afterTrading/MI_INDEX"
            or parse_qs(u.query)!={k:[v] for k,v in params.items()}):
        raise ValueError("MI_INDEX original daily source not official exact HTTPS request")
    raw=response.content
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_HTTP_RESPONSE_BYTES:
        raise ValueError("TWSE official daily market source response oversized")
    body=response.json()
    if not isinstance(body,dict):
        raise ValueError("TWSE official daily market source not a JSON object")
    digest=sha256(raw).hexdigest()
    if body.get("stat")!="OK":
        if not isinstance(body.get("stat"),str) or len(body["stat"])>180:
            raise ValueError("Untrusted official daily market non-OK response")
        return {"date":day,"sha256":digest,"status":"NON_OK",
                "per_issuer":{}}
    tables=body.get("tables")
    if not isinstance(tables,list) or not 1<=len(tables)<=40:
        raise ValueError("TWSE official daily source missing expected trading tables")
    found={}
    compatible=0
    for table in tables:
        if not isinstance(table,dict):
            raise ValueError("Invalid TWSE official daily table")
        fields=table.get("fields",[])
        data=table.get("data",[])
        if (not isinstance(fields,list) or
                not isinstance(data,list) or len(data)>5000):
            raise ValueError("TWSE official daily table unbounded")
        if not all(x in fields for x in ("證券代號","成交股數","收盤價")):
            continue
        compatible+=1
        si=fields.index("證券代號")
        vi=fields.index("成交股數")
        ci=fields.index("收盤價")
        for item in data:
            if not isinstance(item,list) or len(item)!=len(fields):
                raise ValueError("Malformed daily official stock market row")
            sid=str(item[si]).strip()
            if not re.fullmatch(r"\d{4}",sid) or sid=="1589":
                continue
            if sid in found:
                raise ValueError("Duplicate stock in official daily trading tables")
            close=_decimal(item[ci])
            volume=_decimal(item[vi])
            found[sid]=(
                "VALID_POSITIVE_CLOSE" if close is not None and close>0
                and volume is not None and volume>=0 else
                "LISTED_BUT_UNPRICED_OR_UNVERIFIABLE")
    if compatible==0:
        raise ValueError("Official MI_INDEX trading source lacks stock/close table")
    return {"date":day,"sha256":digest,"status":"OK",
            "per_issuer":found}


def reconcile_two_unpriced_windows(prior,daily):
    uncertain,days=validate_prior_owner_uncertain_monthly_report(prior)
    if not isinstance(daily,dict) or set(daily)!=set(days):
        raise ValueError("MI_INDEX does not cover each previous unpriced day")
    out=[]
    categories=Counter()
    for sid,day in uncertain:
        proof=daily[day]
        if (not isinstance(proof,dict) or proof.get("date")!=day or
                not re.fullmatch(r"[0-9a-f]{64}",str(proof.get("sha256","")))
                or proof.get("status") not in ("OK","NON_OK")
                or not isinstance(proof.get("per_issuer"),dict)):
            raise ValueError("Unverified independent official daily MI_INDEX response")
        if proof["status"]=="NON_OK":
            result="MI_INDEX_DAY_RESPONSE_NOT_VERIFIABLE"
        else:
            result=proof["per_issuer"].get(
                sid,"MI_INDEX_NO_STOCK_ROW_NOT_PROOF_OF_HALT")
        if result not in (
                "MI_INDEX_DAY_RESPONSE_NOT_VERIFIABLE",
                "MI_INDEX_NO_STOCK_ROW_NOT_PROOF_OF_HALT",
                "VALID_POSITIVE_CLOSE",
                "LISTED_BUT_UNPRICED_OR_UNVERIFIABLE"):
            raise ValueError("Untrusted issuer day official source classification")
        categories[result]+=1
        out.append({
            "stock_id":sid,
            "original_monthly_stock_day_unverified_close_date":day.isoformat(),
            "independent_daily_all_stock_observation":result,
            "official_daily_source_sha256":proof["sha256"],
            "confirmed_exchange_halt":False,
            "confirmed_missing_bar_should_be_backfilled":False,
        })
    if sum(categories.values())!=len(uncertain):
        raise ValueError("Two owner windows cross-source result does not conserve days")
    return {
        "schema_version":1,"scope":SCOPE,
        "prior_owner_unpriced_2022_long_gap_window_count":2,
        "prior_owner_2022_all_long_source_gaps":30,
        "prior_owner_2022_unobserved_stock_source_date_pairs":804,
        "individual_unpriced_official_stock_day_dates_to_crosscheck":len(uncertain),
        "independent_official_market_daily_requests":len(days),
        "source_date_observation_classes":dict(sorted(categories.items())),
        "owner_private_second_source_daily_date_checks":out,
        "original_stock_day_and_daily_mi_index_are_both_twse_sources_not_fully_independent":True,
        "official_no_close_or_missing_row_does_not_certify_formal_halt":True,
        "individual_ohlcv_or_total_return_certified":False,
        "no_halt_or_backfill_authorization":True,
        "model_release":"BLOCKED",
        "neon_reads":0,"production_neon_writes":0,
        "line_messages_sent":0,"paid_source_used":False,
    }


def main():
    p=argparse.ArgumentParser(
        description="Check TWSE daily MI_INDEX source presence for 2 PR239 owner long-gap windows with unpriced monthly official rows")
    p.add_argument("--prior-239-month-report",required=True)
    p.add_argument("--out",required=True)
    args=p.parse_args()
    try:
        source=_private_file(args.prior_239_month_report,should_exist=True)
        out=_private_file(args.out,should_exist=False)
        if source==out or source.stat().st_size>MAX_SOURCE_REPORT_BYTES:
            raise ValueError("Previously accepted monthly source report missing")
        prior=json.loads(source.read_text(encoding="utf-8"))
        _,days=validate_prior_owner_uncertain_monthly_report(prior)
        proof={d:fetch_official_all_stock_source_day(d) for d in days}
        result=reconcile_two_unpriced_windows(prior,proof)
        payload=json.dumps(result,ensure_ascii=False,indent=2,
                           allow_nan=False)+"\n"
        if len(payload.encode("utf-8"))>MAX_OUTPUT_BYTES:
            raise ValueError("Private second-source report exceeded maximum")
        with out.open("x",encoding="utf-8") as f:
            f.write(payload)
        print(json.dumps({
            "status":"TWSE_2022_TWO_UNPRICED_LONG_GAPS_SECOND_SOURCE_DAY_CHECK_PASS",
            "unpriced_source_day_pairs_crosschecked":len(
                result["owner_private_second_source_daily_date_checks"]),
            "official_daily_calls":len(days),
            "source_date_observation_classes":result[
                "source_date_observation_classes"],
            "confirmed_halts":0,"neon_writes":0,
            "line_messages_sent":0,"model_release":"BLOCKED",
        },ensure_ascii=False))
    except Exception:
        raise SystemExit(
            "2022 2 unpriced-gap TWSE second source evidence FAILED; "
            "Neon and LINE untouched and no price or credentials printed"
        ) from None


if __name__=="__main__":
    main()
