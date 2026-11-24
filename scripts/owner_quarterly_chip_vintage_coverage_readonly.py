"""Read-only chip source maturity/vintage coverage on the frozen dual-market panel.

Counts only; no scores or forward labels. Retained retrieved_at before the
Taipei signal day is a conservative necessary evidence check, NOT publication
timestamp, immutable version history, exact price alignment or PIT proof.
"""
from collections import Counter, defaultdict
from datetime import date
import argparse
import json
import os

from scripts import owner_twse_tpex_quarterly_panel_merge_offline as m

PANEL_HASH="1e91e55a13385507e3b19cb77c72c4d22a6d652b8b50e28b0063d33f947646cf"
COMPONENTS=("institutional","margin","tdcc","insider")
WEIGHTS=(40,25,25,10)
MIN_DATES=(20,2,2,1)
FRESH=(7,7,21,120)
RANGES=("1-999","1,000-5,000","5,001-10,000","10,001-15,000","15,001-20,000",
    "20,001-30,000","30,001-40,000","40,001-50,000","50,001-100,000","100,001-200,000",
    "200,001-400,000","400,001-600,000","600,001-800,000","800,001-1,000,000","1,000,001以上")
TAGS={
    "twse":("TWSE_T86","TWSE_MI_MARGN","TWSE_t187ap11_L"),
    "tpex":("TPEX_OPENAPI_tpex_3insti_daily_trading","TPEX_tpex_mainboard_margin_balance","TPEX_mopsfin_t187ap11_O")
}
# For every source date, retain ALL rows in the group when assessing validity
# and vintage; do not turn a partial weekly/monthly snapshot into evidence.
SQL="""
WITH params AS (
 SELECT %s::text AS market,%s::date AS signal,%s::text[] AS ids,
        %s::text AS itag,%s::text AS mtag,%s::text AS xtag,%s::text[] AS ranges
), source_dates AS (
 SELECT 'institutional' AS component,p.stock_id,p.trade_date AS d,
   BOOL_AND(COALESCE(p.source=a.itag AND p.total_net IS NOT NULL,false)) AS valid,
   BOOL_AND(COALESCE(p.retrieved_at < (a.signal::timestamp AT TIME ZONE 'Asia/Taipei'),false)) AS retained
 FROM public.institutional_flows p CROSS JOIN params a
 WHERE p.market=a.market AND p.stock_id=ANY(a.ids)
 AND p.trade_date>=a.signal-45 AND p.trade_date<a.signal
 GROUP BY p.stock_id,p.trade_date
 UNION ALL
 SELECT 'margin',p.stock_id,p.trade_date,
   BOOL_AND(COALESCE(p.source=a.mtag AND p.margin_balance>=0 AND p.short_balance>=0,false)),
   BOOL_AND(COALESCE(p.retrieved_at < (a.signal::timestamp AT TIME ZONE 'Asia/Taipei'),false))
 FROM public.margin_short p CROSS JOIN params a
 WHERE p.market=a.market AND p.stock_id=ANY(a.ids)
 AND p.trade_date>=a.signal-21 AND p.trade_date<a.signal
 GROUP BY p.stock_id,p.trade_date
 UNION ALL
 SELECT 'tdcc',p.stock_id,p.as_of_date,
   COUNT(DISTINCT p.holder_range)=15 AND BOOL_AND(COALESCE(p.source='TDCC_OPEN_DATA_1_5'
     AND p.share_percent BETWEEN 0 AND 100,false)),
   BOOL_AND(COALESCE(p.retrieved_at < (a.signal::timestamp AT TIME ZONE 'Asia/Taipei'),false))
 FROM public.tdcc_share_distribution p CROSS JOIN params a
 WHERE p.market=a.market AND p.stock_id=ANY(a.ids) AND p.holder_range=ANY(a.ranges)
 AND p.as_of_date>=a.signal-42 AND p.as_of_date<a.signal
 GROUP BY p.stock_id,p.as_of_date
 UNION ALL
 SELECT 'insider',p.stock_id,p.as_of_date,
   BOOL_AND(COALESCE(p.source=a.xtag AND p.share_count>=0 AND p.pledged_shares>=0
     AND p.pledged_shares<=p.share_count,false)) AND COALESCE(SUM(p.share_count),0)>0,
   BOOL_AND(COALESCE(p.retrieved_at < (a.signal::timestamp AT TIME ZONE 'Asia/Taipei'),false))
 FROM public.insider_holdings p CROSS JOIN params a
 WHERE p.market=a.market AND p.stock_id=ANY(a.ids)
 AND p.as_of_date>=a.signal-120 AND p.as_of_date<a.signal
 GROUP BY p.stock_id,p.as_of_date
)
SELECT component,stock_id,
 COUNT(*) FILTER(WHERE valid)::int, MAX(d) FILTER(WHERE valid),
 COUNT(*) FILTER(WHERE valid AND retained)::int, MAX(d) FILTER(WHERE valid AND retained)
FROM source_dates GROUP BY component,stock_id
ORDER BY component,stock_id
LIMIT 8001
"""


def verify_input(payload):
    if type(payload) is not dict or set(payload)!={"summary","private_feature_rows"}:
        raise ValueError("Invalid merged panel")
    s=payload["summary"];rows=payload["private_feature_rows"]
    if (s.get("scope")!="OWNER_TWSE_TPEX_MERGED_QUARTERLY_RAW_FEATURE_PANEL"
        or s.get("private_feature_rows_sha256")!=PANEL_HASH or s.get("model_release")!="BLOCKED"
        or len(rows)!=24873 or m.fingerprint(rows)!=PANEL_HASH
        or s.get("forward_labels_created") is not False or s.get("chip_factors_integrated") is not False):
        raise ValueError("Frozen owner panel changed")
    groups=defaultdict(list)
    for market in ("twse","tpex"):
        part=[r for r in rows if r["market"]==market]
        counts,ids=m.check_rows(part,market)
        if len(part)!=m.SPECS[market][2] or m.fingerprint(part)!=m.SPECS[market][3]:
            raise ValueError("Original market panel changed")
        for r in part:
            groups[market,r["signal_date"]].append(r["stock_id"])
    if sum(map(len,groups.values()))!=24873 or len(groups)!=34:
        raise ValueError("Unexpected panel key partition")
    return groups


def classify(ids,signal,rows):
    if (type(signal) is not date or not ids or len(ids)>1092 or len(set(ids))!=len(ids)
        or len(rows)>4*len(ids)):
        raise ValueError("Invalid bounded coverage query")
    allowed=set(ids);index={}
    for component,sid,n,latest,k,retained in rows:
        if (component not in COMPONENTS or sid not in allowed or (component,sid) in index
            or type(n) is not int or type(k) is not int or not 0<=k<=n<=120
            or (n==0)!=(latest is None) or (k==0)!=(retained is None)
            or any(type(d) is not date or not 0<(signal-d).days<=120 for d in (latest,retained) if d is not None)
            or retained is not None and retained>latest):
            raise ValueError("Invalid aggregate source evidence")
        index[component,sid]=(n,latest,k,retained)
    potential=Counter();strict=Counter();counts=Counter();strict_counts=Counter()
    for sid in ids:
        w=0;v=0
        for c,minimum,fresh,weight in zip(COMPONENTS,MIN_DATES,FRESH,WEIGHTS):
            n,last,k,kept=index.get((c,sid),(0,None,0,None))
            if n>=minimum and (signal-last).days<=fresh:
                potential[c]+=1;w+=weight
            if k>=minimum and (signal-kept).days<=fresh:
                strict[c]+=1;v+=weight
        counts[w]+=1;strict_counts[v]+=1
    if any(strict[c]>potential[c] for c in COMPONENTS):
        raise RuntimeError("Retained vintage coverage exceeds present coverage")
    return {"candidate_rows":len(ids),
        "present_source_maturity_candidates":{c:potential[c] for c in COMPONENTS},
        "retained_before_signal_candidates":{c:strict[c] for c in COMPONENTS},
        "present_candidate_weight_at_least_50":sum(n for w,n in counts.items() if w>=50),
        "retained_candidate_weight_at_least_50":sum(n for w,n in strict_counts.items() if w>=50),
        "present_all_four_candidates":counts[100],"retained_all_four_candidates":strict_counts[100]}


def capture(url,groups):
    import psycopg
    if not isinstance(url,str) or not url.startswith(("postgres://","postgresql://")):
        raise ValueError("Protected local URL required")
    reports=[]
    with psycopg.connect(url,connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute("SET LOCAL statement_timeout='45s'")
            for (market,day),ids in sorted(groups.items()):
                signal=date.fromisoformat(day)
                cur.execute(SQL,(market,signal,ids,*TAGS[market],list(RANGES)))
                result=classify(ids,signal,cur.fetchall())
                reports.append(dict(result,market=market,signal_date=day))
        conn.rollback()
    return reports


def summarize(reports):
    if (len(reports)!=34 or sum(r["candidate_rows"] for r in reports)!=24873
        or {(r["market"],r["signal_date"]) for r in reports}!={(x,d) for x in ("twse","tpex") for d in m.DATES}):
        raise ValueError("Coverage report partition mismatch")
    totals={}
    for market in ("twse","tpex","all"):
        subset=[r for r in reports if market=="all" or r["market"]==market]
        totals[market]={"candidate_rows":sum(r["candidate_rows"] for r in subset)}
        for field in ("present_source_maturity_candidates","retained_before_signal_candidates"):
            totals[market][field]={c:sum(r[field][c] for r in subset) for c in COMPONENTS}
        for field in ("present_candidate_weight_at_least_50","retained_candidate_weight_at_least_50","present_all_four_candidates","retained_all_four_candidates"):
            totals[market][field]=sum(r[field] for r in subset)
    return {"schema_version":1,"scope":"OWNER_DUAL_MARKET_QUARTERLY_CHIP_SOURCE_MATURITY_VINTAGE_COVERAGE",
        "coverage":totals,"market_signal_outcomes":reports,"chip_scores_computed":False,
        "chip_factors_integrated":False,"historical_publication_times_independently_proven":False,
        "immutable_source_vintage_history_verified":False,"exact_price_window_alignment_verified":False,
        "candidate_weight_is_not_publishable_chip_score":True,"strict_cutoff":"before_signal_day_00_00_Asia_Taipei",
        "production_neon_writes":0,"line_messages_sent":0,"paid_upgrade_requested":False,"model_release":"BLOCKED"}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--panel",required=True);p.add_argument("--out",required=True)
    a=p.parse_args();stage="PANEL"
    try:
        source=m.private_path(a.panel,existing=True);out=m.private_path(a.out,existing=False)
        payload,digest=m.read_panel(source)
        groups=verify_input(payload)
        stage="NEON_READONLY_COVERAGE"
        result=summarize(capture(os.environ.get("DATABASE_URL",""),groups))
        result["input_panel_sha256"]=digest
        stage="PRIVATE_OUTPUT"
        with out.open("x",encoding="utf-8") as f:
            json.dump(result,f,indent=2,allow_nan=False);f.write("\n")
        # Full date outcomes remain local; only compact coverage totals printed.
        print(json.dumps({k:v for k,v in result.items() if k!="market_signal_outcomes"},allow_nan=False))
    except Exception:
        raise SystemExit("FAILED safely; diagnostic_stage="+stage+"; no Neon writes or LINE action") from None


if __name__=="__main__":
    main()
