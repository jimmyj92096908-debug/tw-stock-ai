"""Whole-market OFFICIAL ex-right/dividend candidate parser, bounded 31 days.

New evidence-only pipeline: does NOT edit the production 4-stock
corporate_actions importer, adjust price bars or treat reference-price
differences as audited cash dividend total returns. As-of capture timestamps
are fresh observations, NEVER retroactively original issuer announcement time.
"""
from __future__ import annotations

from datetime import date,datetime,timezone
from hashlib import sha256
from pathlib import Path
import argparse,json,math,os,re

import psycopg
from psycopg.rows import dict_row
import requests

from src.corporate_actions_data import (
    TWSE_EX_URL,TWSE_REDUCTION_URL,TPEX_EX_URL,TPEX_REDUCTION_URL,
    TPEX_EX_LEGACY_URL,TPEX_EX_COLUMNS,
    _pick,_number,unpack
)

SOURCES={
    "twse":{"ex":TWSE_EX_URL,"reduction":TWSE_REDUCTION_URL},
    "tpex":{"ex":TPEX_EX_URL,"reduction":TPEX_REDUCTION_URL},
}
STOCK_SQL="""SELECT market,stock_id FROM public.stock_master
WHERE market IN ('twse','tpex')"""
EXISTING_SQL="""SELECT market,COUNT(*)::int AS existing_rows,
COUNT(DISTINCT stock_id)::int AS stocks
FROM public.corporate_actions
GROUP BY market"""
MAX_RETURNED_EVENTS=8000
MAX_JSON_BYTES=4_000_000

def _read_rows(url,params,*,get=requests.get):
    if not url.startswith(("https://www.twse.com.tw/","https://www.tpex.org.tw/")):
        raise ValueError("Only official TWSE TPEx query endpoints")
    resp=get(url,params=params,timeout=(10,35),headers={
        "User-Agent":"tw-stock-ai/free-official-dividend-research",
        "Accept":"application/json"})
    resp.raise_for_status()
    payload=resp.json()
    if isinstance(payload,list) and not payload:
        return []
    if isinstance(payload,dict) and any(
        isinstance(payload.get(k),list) and not payload[k]
        for k in ("data","aaData","records")
    ):
        return []
    return unpack(payload)

def fetch_month(start,end,*,fetcher=_read_rows):
    if type(start) is not date or type(end) is not date or (
        start>end or (end-start).days>30 or end>datetime.now(timezone.utc).date()):
        raise ValueError("Official month window must be 1..31 actual past days")
    s=start.isoformat();e=end.isoformat()
    date_args={"startDate":s.replace("-","/"),
               "endDate":e.replace("-","/"),"response":"json"}
    eight_args={"startDate":s.replace("-",""),
                "endDate":e.replace("-",""),"response":"json"}
    tw_ex=fetcher(TWSE_EX_URL,eight_args)
    tw_red=fetcher(TWSE_REDUCTION_URL,eight_args)
    source_tpex_ex=TPEX_EX_URL
    try:
        tp_ex=fetcher(TPEX_EX_URL,date_args)
    except (requests.exceptions.RequestException,ValueError):
        roc=lambda d:f"{d.year-1911}/{d.month:02d}/{d.day:02d}"
        source_tpex_ex=TPEX_EX_LEGACY_URL
        tp_ex=fetcher(TPEX_EX_LEGACY_URL,{
            "l":"zh-tw","d":roc(start),"ed":roc(end)})
    tp_red=fetcher(TPEX_REDUCTION_URL,date_args)
    groups={
        ("twse","ex",TWSE_EX_URL):tw_ex,
        ("twse","reduction",TWSE_REDUCTION_URL):tw_red,
        ("tpex","ex",source_tpex_ex):tp_ex,
        ("tpex","reduction",TPEX_REDUCTION_URL):tp_red
    }
    if any(not isinstance(v,list) or len(v)>MAX_RETURNED_EVENTS for v in groups.values()):
        raise ValueError("Unbounded or malformed exchange ex-right/reduction feed")
    return groups

def _parse_official_event_date(value, *, market, kind, symbol):
    """Parse whole-day official event dates; never guess month/day from partial dates.

    Exchange feeds contain both ROC and Gregorian dates, including unseparated
    7-/8-digit numbers. The shared historic parser's regex can misinterpret
    compact ROC dates by greedily reading four year digits.
    """
    raw=str(value or "").strip()
    separated=re.fullmatch(
        r"([0-9]{2,4})[年./-]([0-9]{1,2})[月./-]([0-9]{1,2})日?",raw)
    if separated:
        y,m,d=map(int,separated.groups())
    elif re.fullmatch(r"[0-9]{6,8}",raw):
        y,m,d=int(raw[:-4]),int(raw[-4:-2]),int(raw[-2:])
    else:
        raise ValueError(
            f"Unsupported {market}/{kind} official event date for stock "
            f"{symbol}: {raw[:48]!r} (requires complete Y/M/D)")
    if not 1<=y<=2100:
        raise ValueError(
            f"Invalid {market}/{kind} official event year for stock "
            f"{symbol}: {raw[:48]!r}")
    if y<1911:
        y+=1911
    if y>2100:
        raise ValueError(
            f"Out-of-range {market}/{kind} event year for stock "
            f"{symbol}: {raw[:48]!r}")
    try:
        return date(y,m,d)
    except ValueError as exc:
        raise ValueError(
            f"Invalid {market}/{kind} official event calendar date for stock "
            f"{symbol}: {raw[:48]!r}") from exc


def _candidate(raw,*,market,kind,source,observed_at,start,end,current_set):
    if not isinstance(raw,dict):
        raise ValueError("Official event row not a map")
    sym=str(_pick(raw,["股票代號","證券代號","代號",
                        "Code","SecuritiesCompanyCode"]) or "").strip()
    if not re.fullmatch(r"\d{4}",sym):
        return None
    day_raw=_pick(raw,[
        "除權息日期","除權日期","恢復買賣日期",
        "恢復交易日期","資料日期","日期","Date"])
    if day_raw is None:
        raise ValueError("Official issuer event lacks effective date")
    actual=_parse_official_event_date(day_raw,market=market,kind=kind,symbol=sym)
    if actual<start or actual>end:
        raise ValueError("Official response has event outside requested month")
    if kind=="ex":
        prev=_number(_pick(raw,["除權息前收盤價","除權息前一日收盤價",
                                "前收盤價","除權前收盤價"]))
        ref=_number(_pick(raw,["除權息參考價","除權參考價",
                               "開始交易基準價","參考價"]))
        raw_kind=str(_pick(raw,["權/息","權或息","除權息",
                                "類別","權息別"]) or "")
        label=("CASH_DIVIDEND" if "息" in raw_kind and "權" not in raw_kind
               else "STOCK_DIVIDEND" if "權" in raw_kind and "息" not in raw_kind
               else "COMBINED_OR_UNKNOWN")
        cash=_number(_pick(raw,["現金股利","每股現金股利",
                                "每股配發現金股利"]))
        share_ratio=None
    else:
        label="CAPITAL_REDUCTION"
        prev=_number(_pick(raw,["停止買賣前收盤價","最後交易日之收盤價格",
                                 "停止買賣前收盤價格","前收盤價"]))
        ref=_number(_pick(raw,["恢復買賣參考價","減資恢復買賣開始日參考價格",
                                "恢復買賣開始日參考價格","參考價"]))
        cash=None
        share_ratio=_number(_pick(raw,["每仟股換發股數","每千股換發股數",
                                        "減資換股率","sharesPerThousand"]))
    if cash is not None and (not math.isfinite(cash) or cash<0):
        raise ValueError("Invalid explicit official cash dividend")
    # The real issuer publication time is not in the market price reference
    # feed; source capture time must NEVER be backdated to actual event date.
    factor=None
    if (prev is not None and ref is not None and
        math.isfinite(prev) and math.isfinite(ref) and prev>0 and ref>0):
        factor=round(ref/prev,12)
    if share_ratio is not None and (not math.isfinite(share_ratio) or
        not 0<share_ratio<=1000):
        raise ValueError("Invalid officially reported share exchange ratio")
    source_sha=sha256(json.dumps(raw,ensure_ascii=False,sort_keys=True,
                               default=str,separators=(",",":")).encode()).hexdigest()
    return {
        "market":market,"stock_id":sym,"ex_date":actual.isoformat(),
        "action_type_candidate":label,
        "reference_price_factor_if_available":factor,
        "explicit_cash_dividend_per_share":cash,
        "share_exchange_per_thousand_if_available":share_ratio,
        "official_source":source,
        "source_raw_record_sha256":source_sha,
        "first_observed_at_utc":observed_at.astimezone(timezone.utc).isoformat(),
        "in_today_current_master":(market,sym) in current_set,
        "issuer_original_announcement_time_verified":False,
        "historical_total_return_adjustment_verified":False,
    }

def assess(groups,*,start,end,observed_at,current_stocks,existing_counts):
    if type(start) is not date or type(end) is not date or start>end:
        raise ValueError("Real ex-right query dates required")
    if not isinstance(observed_at,datetime) or observed_at.tzinfo is None:
        raise ValueError("True observed archive time required")
    if not isinstance(current_stocks,set) or len(current_stocks)<1500:
        raise ValueError("Missing current official master controls")
    if not isinstance(existing_counts,list):
        raise ValueError("Known production company actions count required")
    source_counts=[]
    rows=[]
    for (market,kind,source),raw in sorted(groups.items()):
        if market not in SOURCES or kind not in ("ex","reduction") or (
            source!=SOURCES[market][kind] and not (
                market=="tpex" and kind=="ex" and source==TPEX_EX_LEGACY_URL
            )):
            raise ValueError("Unverified exchange source provenance")
        if not isinstance(raw,list) or len(raw)>MAX_RETURNED_EVENTS:
            raise ValueError("Oversized official event response")
        matched=0
        out_of_requested_range=0
        for item in raw:
            if not isinstance(item,dict):
                raise ValueError("Malformed official event row")
            symbol=str(_pick(item,["股票代號","證券代號","代號",
                                   "Code","SecuritiesCompanyCode"]) or "").strip()
            if re.fullmatch(r"\d{4}",symbol):
                date_raw=_pick(item,["除權息日期","除權日期","恢復買賣日期",
                                    "恢復交易日期","資料日期","日期","Date"])
                if date_raw is None:
                    raise ValueError("Official event missing effective date")
                raw_day=_parse_official_event_date(date_raw,market=market,kind=kind,symbol=symbol)
                if not start<=raw_day<=end:
                    # Some public endpoints ignore their query parameters.
                    # Reject out-of-window rows from the requested evidence
                    # WITHOUT falsely claiming the whole feed is this month.
                    out_of_requested_range+=1
                    continue
            candidate=_candidate(item,market=market,kind=kind,source=source,
                observed_at=observed_at,start=start,end=end,
                current_set=current_stocks)
            if candidate is not None:
                rows.append(candidate);matched+=1
        source_counts.append({"market":market,"kind":kind,
           "source":source,"received_rows":len(raw),
           "four_digit_candidates":matched,
           "excluded_outside_requested_date_range":out_of_requested_range,
           "excluded_non_common_stock_or_unknown":len(raw)-matched-out_of_requested_range})
    if len(source_counts)!=4:
        raise ValueError("Must verify four official market/type source responses")
    if len(rows)>MAX_RETURNED_EVENTS:
        raise ValueError("Event preview cap reached")
    # Only group exact same event economic/date factor; raw feed duplicate
    # sources may be reported but must never be double-applied.
    unique={}
    for r in rows:
        key=(r["market"],r["stock_id"],r["ex_date"],r["action_type_candidate"],
             r["reference_price_factor_if_available"],
             r["explicit_cash_dividend_per_share"],
             r["share_exchange_per_thousand_if_available"])
        unique.setdefault(key,r)
    report={
        "schema_version":1,
        "scope":"TWSE_TPEX_CURRENT_OFFICIAL_EXRIGHT_MONTHLY_EVIDENCE_NOT_TOTAL_RETURN",
        "query_from":start.isoformat(),"query_to":end.isoformat(),
        "first_seen_at_utc":observed_at.astimezone(timezone.utc).isoformat(),
        "source_evidence":source_counts,
        "raw_four_digit_source_events":len(rows),
        "distinct_candidate_economic_events":len(unique),
        "duplicate_economic_feed_records":len(rows)-len(unique),
        "outside_today_stock_master_candidates":sum(
             not r["in_today_current_master"] for r in unique.values()),
        "explicit_cash_amount_candidate_rows":sum(
             r["explicit_cash_dividend_per_share"] is not None for r in unique.values()),
        "unverified_reference_price_factors":sum(
             r["reference_price_factor_if_available"] is None for r in unique.values()),
        "existing_corporate_actions_by_market":existing_counts,
        "candidates":list(unique.values()),
        "no_historical_issuer_publication_vintages_in_feed":True,
        "not_full_five_year_issuer_or_dividend_coverage":True,
        "raw_price_labels_still_unadjusted":True,
        "verified_total_return_labels":False,
        "production_corporate_actions_modified":False,
        "permanent_adjusted_price_rows_created":0,
        "database_writes":0,
        "LINE_or_trading_enabled":False,
        "paid_data_used":False,
    }
    if len(json.dumps(report,ensure_ascii=False).encode())>MAX_JSON_BYTES:
        raise ValueError("Month of full-market source events exceeds free bounded report")
    return report

def preview(url,*,start,end,report_path=None,fetcher=fetch_month):
    if not url:
        raise ValueError("Existing protected Neon DB URL is required")
    with psycopg.connect(url,connect_timeout=15,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='30000ms'")
        members={(r["market"],r["stock_id"]) for r in
                 conn.execute(STOCK_SQL).fetchall()}
        existing=[dict(x) for x in conn.execute(EXISTING_SQL).fetchall()]
    groups=fetcher(start,end)
    result=assess(groups,start=start,end=end,observed_at=datetime.now(timezone.utc),
                  current_stocks=members,existing_counts=existing)
    if report_path:
        target=Path(report_path);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result

def main():
    p=argparse.ArgumentParser(description="Read-only one-month official whole-market dividend events research")
    p.add_argument("--from-date",type=date.fromisoformat,required=True)
    p.add_argument("--to-date",type=date.fromisoformat,required=True)
    p.add_argument("--report",type=Path,default=Path("official-dividend-month-evidence.json"))
    a=p.parse_args()
    result=preview(os.getenv("DATABASE_URL",""),start=a.from_date,
                   end=a.to_date,report_path=a.report)
    print(json.dumps({k:result[k] for k in (
        "source_evidence","raw_four_digit_source_events",
        "distinct_candidate_economic_events",
        "outside_today_stock_master_candidates",
        "explicit_cash_amount_candidate_rows",
        "verified_total_return_labels","database_writes")},ensure_ascii=False))

if __name__=="__main__":
    main()
