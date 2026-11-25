"""Owner-local monthly research CLI, with frozen quarterly anchor replay.

Only hypothetical research. A file hash binds bytes, not independent proof of
publication vintage or complete corporate-action coverage. No DB/network calls.
Inputs must be produced separately; this CLI does not fabricate observations.
"""
import argparse
from collections import Counter,defaultdict
from datetime import date
from hashlib import sha256
import json
import math

from scripts import owner_twse_tpex_quarterly_panel_merge_offline as m
from scripts import owner_quarterly_chip_vintage_coverage_readonly as chip
from src import research_monthly_ridge_hypothetical as ridge
from src import research_monthly_risk_receipt as risk

CUTOFF="2026-11-20"
MAX_STOCKS=20
REASONS={"MISSING_COMPLETE_PRICE_PATH","ACTION_COVERAGE_UNPROVEN",
         "UNMATURED_AT_CUTOFF","INSUFFICIENT_FEATURE_COHORT"}
MONTHS=[(2022,12)]+[(y,j) for y in range(2023,2027) for j in range(1,12 if y==2026 else 13)]


def validate_monthly(payload,quarterly):
    if type(payload) is not dict or set(payload)!={"summary","sample_stock_ids","private_feature_rows"}:
        raise ValueError("Expected private monthly pilot envelope")
    s=payload["summary"];ids=payload["sample_stock_ids"];rows=payload["private_feature_rows"]
    if (type(s) is not dict or type(ids) is not list or not 5<=len(ids)<=MAX_STOCKS
        or any(type(x) is not str or not m.CODE.fullmatch(x) or x=="1589" for x in ids)
        or ids!=sorted(set(ids)) or type(rows) is not list or not 1<=len(rows)<=48*len(ids)):
        raise ValueError("Invalid pilot scope")
    market=s.get("market")
    if market not in ("twse","tpex"):
        raise ValueError("Unknown market")
    exact={"schema_version":1,"scope":"OWNER_MONTHLY_RAW_FEATURE_PILOT_OFFLINE",
        "candidate_stocks":len(ids),"requested_signal_dates":48,
        "candidate_stock_signal_pairs":48*len(ids),"accepted_feature_rows":len(rows),
        "accepted_feature_values":len(rows)*len(m.FEATURES),"feature_version":m.VERSION,
        "feature_names":m.FEATURES,"quarterly_anchor_exact":True,
        "private_feature_rows_sha256":m.fingerprint(rows),
        "prefix_only_feature_computation":True,"official_market_calendar_independently_proven":False,
        "current_roster_not_historical_pit":True,"forward_labels_created":False,
        "corporate_actions_adjusted":False,"model_trained":False,"production_neon_reads":0,
        "production_neon_writes":0,"line_messages_sent":0,"paid_upgrade_requested":False,"model_release":"BLOCKED"}
    if any(type(s.get(k)) is not type(v) or s[k]!=v for k,v in exact.items()):
        raise ValueError("Monthly summary contract mismatch")
    outcomes=s.get("signal_date_outcomes")
    if type(outcomes) is not list or len(outcomes)!=48:
        raise ValueError("Missing declared monthly schedule")
    dates=[];counts=Counter()
    for o in outcomes:
        if type(o) is not dict or set(o)!={"signal_date","accepted","excluded"}:
            raise ValueError("Invalid month outcome")
        d=ridge.day(o["signal_date"])
        n=o["accepted"];e=o["excluded"]
        if (type(n) is not int or not 0<=n<=len(ids) or type(e) is not dict
            or any(type(k) is not str or type(v) is not int or v<=0 for k,v in e.items())
            or n+sum(e.values())!=len(ids) or d.weekday()>=5):
            raise ValueError("Unreconciled monthly coverage")
        dates.append(o["signal_date"]);counts[o["signal_date"]]=n
    if ([(date.fromisoformat(d).year,date.fromisoformat(d).month) for d in dates]!=MONTHS
        or dates[-1]!=CUTOFF or not set(m.DATES)<=set(dates)):
        raise ValueError("Fixed schedule changed")
    keys=[];actual=Counter()
    for r in rows:
        if type(r) is not dict or set(r)!=m.ROW_KEYS:
            raise ValueError("Unexpected monthly row schema")
        d=r["signal_date"];v=r["feature_vector"]
        if (r["market"]!=market or r["stock_id"] not in ids or d not in counts
            or type(v) is not list or len(v)!=len(m.FEATURES)
            or any(type(x) not in (int,float) or not math.isfinite(x) for x in v)
            or type(r["prefix_source_rows"]) is not int or not 240<=r["prefix_source_rows"]<=1600
            or type(r["prefix_source_sha256"]) is not str or not m.HASH.fullmatch(r["prefix_source_sha256"])):
            raise ValueError("Invalid monthly feature evidence")
        keys.append((d,r["stock_id"]));actual[d]+=1
    if keys!=sorted(set(keys)) or any(actual[d]!=counts[d] for d in dates):
        raise ValueError("Duplicate or missing accepted feature row")
    prior=[r for r in quarterly if r["market"]==market and r["stock_id"] in ids]
    replay=[r for r in rows if r["signal_date"] in m.DATES]
    if (not prior or prior!=replay or s.get("quarterly_anchor_rows_replayed")!=len(prior)
        or s.get("quarterly_anchor_sha256")!=m.fingerprint(prior)):
        raise ValueError("Frozen quarterly anchors not reproduced")
    return rows,dates,counts


def evaluate_bundle(monthly,observations,quarterly,*,test_start):
    rows,dates,counts=validate_monthly(monthly,quarterly)
    if (type(observations) is not dict or set(observations)!={"schema_version","scope","observations","excluded_signal_dates"}
        or observations["schema_version"]!=1 or observations["scope"]!="OWNER_HYPOTHETICAL_ECONOMIC_OBSERVATIONS"
        or type(observations["observations"]) is not list or len(observations["observations"])>len(rows)
        or type(observations["excluded_signal_dates"]) is not dict):
        raise ValueError("Invalid observation envelope")
    items=observations["observations"];excluded=observations["excluded_signal_dates"]
    by_date=Counter()
    for x in items:
        if type(x) is not dict or x.get("signal_date") not in counts:
            raise ValueError("Foreign observation date")
        by_date[x["signal_date"]]+=1
    for d in dates:
        if d in excluded:
            reason=excluded[d]
            if reason not in REASONS or by_date[d]!=0:
                raise ValueError("Invalid excluded signal")
            if (reason=="INSUFFICIENT_FEATURE_COHORT")!=(counts[d]<5):
                raise ValueError("Insufficient cohort reason mismatch")
            if reason=="UNMATURED_AT_CUTOFF" and d!=CUTOFF:
                raise ValueError("Unexpected unmatured date assertion")
        elif counts[d]<5 or by_date[d]!=counts[d]:
            raise ValueError("Missing or partial declared observation cohort")
    if set(excluded)-set(dates) or CUTOFF not in excluded:
        raise ValueError("Missing final cutoff exclusion")
    result=ridge.evaluate(rows,items,label_cutoff=CUTOFF,test_start=test_start)
    receipt=risk.audit(result)
    summary={"schema_version":1,"scope":"OWNER_HYPOTHETICAL_MONTHLY_RESEARCH_E2E",
        "market":monthly["summary"]["market"],"monthly_signal_dates":len(dates),
        "accepted_feature_rows":len(rows),"supplied_observation_rows":len(items),
        "declared_exclusion_counts":dict(sorted(Counter(excluded.values()).items())),
        "quarterly_anchor_replayed":True,"hypothetical_model_fitted":result["model_trained"],
        "test_windows":receipt["window_count"],"risk_status":receipt["status"],
        "source_observations_independently_authenticated":False,
        "exclusion_reason_truth_independently_verified":False,
        "approved_total_return_labels":0,"alpha_verified":False,
        "production_neon_reads":0,"production_neon_writes":0,"line_messages_sent":0,
        "paid_upgrade_requested":False,"model_release":"BLOCKED"}
    return {"summary":summary,"evaluation":result,"risk":receipt}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("quarterly","monthly","observations","monthly-sha256","observations-sha256","test-start","out"):
        p.add_argument("--"+key,required=True)
    a=p.parse_args();stage="PRIVATE_INPUT"
    try:
        paths=[m.private_path(getattr(a,k),existing=True) for k in ("quarterly","monthly","observations")]
        out=m.private_path(a.out,existing=False)
        if len(set(paths+[out]))!=4:
            raise ValueError("Distinct private paths required")
        q,hq=m.read_panel(paths[0]);mo,hm=m.read_panel(paths[1]);ob,ho=m.read_panel(paths[2])
        if hm!=a.monthly_sha256.lower() or ho!=a.observations_sha256.lower():
            raise ValueError("Pinned file bytes changed")
        stage="FROZEN_QUARTERLY"
        chip.verify_input(q)
        stage="EVALUATE_HYPOTHETICAL"
        report=evaluate_bundle(mo,ob,q["private_feature_rows"],test_start=a.test_start)
        report["summary"]["input_file_sha256"]=[hq,hm,ho]
        stage="PRIVATE_OUTPUT"
        with out.open("x",encoding="utf-8") as f:
            json.dump(report,f,indent=2,allow_nan=False);f.write("\n")
        print(json.dumps(report["summary"],allow_nan=False))
    except Exception:
        raise SystemExit("FAILED safely; diagnostic_stage="+stage+"; zero Neon writes or LINE actions") from None


if __name__=="__main__":
    main()
