"""Owner-local raw-price-only diagnostic; NOT total-return or release proof.
Pinned actual monthly panel and late source cache; no action-coverage assertion.
Fixed expanding Ridge, 20 prior mature months, minimum 10 test windows.
"""
import argparse
from collections import defaultdict
from datetime import date
import json
import math
from fractions import Fraction
from scripts import owner_five_stock_aes_direct_factor_research_offline as b
from src import research_monthly_ridge_hypothetical as ridge
from src import research_monthly_fold_plan as limits

FEATURE_HASH="ead0a5a84abd93abfa9958457beb4d5ed663e8c8aae227d118a9827dd45927d3"
LATE_HASH="40972bcffec77b8230f8aaea0016b4fc3797a61d572ae61725583fd39a5d6abb"
TEST_START=date(2024,9,1)

def build_paths(stocks,features,late):
    if len(stocks)!=5 or len(set(stocks))!=5 or "1589" in stocks:
        raise ValueError("Fixed five-stock cohort required")
    allowed=set(stocks);groups=defaultdict(dict);prices={}
    for r in late:
        d,s=r["trade_date"],r["stock_id"]
        if (type(d) is not date or not b.START<=d<date(2026,12,1) or d.weekday()>=5
            or s not in allowed or r["market"]!="twse" or r["source"]!="TWSE_STOCK_DAY"
            or b.early.exact_core(r) is None or (d,s) in prices):
            raise ValueError("Invalid or duplicate price")
        prices[d,s]=r["close"]
    calendar=sorted({d for d,s in prices if d<=b.CUTOFF})
    for r in features:
        d=date.fromisoformat(r["signal_date"]);s=r["stock_id"];v=r["feature_vector"]
        if (set(r)!=b.m.ROW_KEYS or d>b.CUTOFF or s not in allowed or r["market"]!="twse"
            or s in groups[d] or len(v)!=12 or any(type(x) not in (int,float) or not math.isfinite(x) for x in v)):
            raise ValueError("Invalid frozen feature")
        groups[d][s]=v
    if len(groups)>48 or len({(d.year,d.month) for d in groups})!=len(groups):
        raise ValueError("Unexpected monthly schedule")
    paths=[];data=[];excluded={}
    for d,g in sorted(groups.items()):
        if set(g)!=allowed:
            excluded[d.isoformat()]="INCOMPLETE_FEATURE_COHORT";continue
        sessions=[s for s in calendar if s>d][:6]
        if len(sessions)!=6:
            excluded[d.isoformat()]="UNMATURED_WINDOW";continue
        if any((s,k) not in prices for s in sessions for k in allowed):
            excluded[d.isoformat()]="MISSING_RAW_PRICE_PATH";continue
        members=[]
        for sid in sorted(allowed):
            closes=[prices[s,sid] for s in sessions]
            ratio=float(Fraction(closes[-1])/Fraction(closes[0]))
            if not 0<ratio<=11:raise ValueError("Return outside research bounds")
            paths.append({"market":"twse","stock_id":sid,"signal_date":d.isoformat(),
                "sessions":[s.isoformat() for s in sessions],
                "raw_closes":[format(x,"f") for x in closes],
                "action_coverage_status":"NOT_VERIFIED"})
            members.append((sid,g[sid],ratio-1,ratio))
        data.append((d,sessions[0],sessions[-1],members))
    return data,paths,excluded

def evaluate(stocks,features,late):
    data,paths,excluded=build_paths(stocks,features,late)
    plan=[];last=None
    for d,entry,exit_,members in data:
        if d<TEST_START:continue
        train=[r for r in data if r[0]<d and r[2]<d]
        if len(train)<limits.MIN_TRAIN_DATES or sum(len(r[3]) for r in train)<limits.MIN_TRAIN_ROWS:continue
        if last is not None and d<=last:continue
        plan.append((d,entry,exit_,members,train));last=exit_
    result=[]
    if len(plan)>=limits.MIN_TEST_WINDOWS:
        for d,entry,exit_,members,train in plan:
            tr=[m for r in train for m in r[3]]
            mu,sd,w,ybar=ridge.fit([r[1] for r in tr],[r[2] for r in tr])
            pred=(ridge.np.asarray([r[1] for r in members])-mu)/sd@w+ybar
            if not ridge.np.all(ridge.np.isfinite(pred)):raise ValueError("Nonfinite prediction")
            best=members[min(range(len(members)),key=lambda i:(-float(pred[i]),members[i][0]))]
            cases=[]
            for slip in ridge.SLIPPAGE_BPS:
                selected=ridge.net_return(best[3],0,slip)
                baseline=sum(ridge.net_return(m[3],0,slip) for m in members)/len(members)
                cases.append({"slippage_each_way_bps":slip,"selected_raw_net":selected,
                    "equal_weight_raw_net":baseline,"raw_net_excess":selected-baseline})
            result.append({"signal_date":d.isoformat(),"entry_date":entry.isoformat(),"exit_date":exit_.isoformat(),
                "training_dates":len(train),"training_rows":len(tr),"last_mature_training_exit":max(r[2] for r in train).isoformat(),
                "fitted_state_sha256":ridge.fingerprint([mu.tolist(),sd.tolist(),w.tolist(),ybar]),
                "selection_sha256":ridge.fingerprint(best[0]),"cost_scenarios":cases})
    report={"scope":"OWNER_RAW_PRICE_ONLY_RIDGE_DIAGNOSTIC","schema_version":1,
        "complete_raw_path_dates":len(data),"raw_price_path_rows":len(paths),
        "excluded_signal_dates":excluded,"test_start":TEST_START.isoformat(),
        "eligible_nonoverlapping_test_windows":len(plan),"evaluated_test_windows":len(result),
        "raw_price_only_model_trained":bool(result),"folds":result,
        "approved_total_return_labels":0,"corporate_action_coverage_verified":False,
        "official_calendar_independently_verified":False,"historical_publication_vintage_verified":False,
        "current_roster_not_historical_pit":True,"source_selection_conditioned_on_later_availability":True,
        "raw_model_may_misstate_economic_returns":True,"production_model_trained":False,
        "production_weights_updated":False,"alpha_verified":False,
        "production_neon_reads":0,"production_neon_writes":0,"line_messages_sent":0,
        "paid_upgrade_requested":False,"model_release":"BLOCKED"}
    if result:
        report["mean_raw_net_excess_worst_cost"]=sum(x["cost_scenarios"][-1]["raw_net_excess"] for x in result)/len(result)
    return report,paths

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("panel","monthly","cache-dir","out"):p.add_argument("--"+k,required=True)
    a=p.parse_args();stage="PINNED_INPUT"
    try:
        payload,_=b.m.read_panel(b.m.private_path(a.panel,existing=True))
        stocks=b.five.select(b.chip.verify_input(payload))
        monthly,_=b.m.read_panel(b.m.private_path(a.monthly,existing=True))
        features=monthly["private_feature_rows"]
        if (b.m.fingerprint(list(stocks))!=b.SAMPLE_HASH or monthly["sample_stock_ids"]!=list(stocks)
            or b.m.fingerprint(features)!=FEATURE_HASH or len(features)!=228):
            raise ValueError("Actual owner feature panel changed")
        out=b.m.private_path(a.out,existing=False)
        stage="LATE_CACHE"
        late,h=b.load_late(stocks,a.cache_dir)
        if h!=LATE_HASH:raise ValueError("Actual owner late cache changed")
        stage="RAW_PRICE_DIAGNOSTIC"
        report,paths=evaluate(stocks,features,late)
        report.update(feature_rows_sha256=FEATURE_HASH,late_response_hashes_sha256=h,
                      private_action_window_paths_sha256=b.m.fingerprint(paths))
        stage="PRIVATE_OUTPUT"
        with out.open("x",encoding="utf-8") as f:
            json.dump({"summary":report,"private_action_window_paths":paths},f,indent=2,allow_nan=False)
            f.write("\n")
        print(json.dumps(report,allow_nan=False))
    except Exception:
        raise SystemExit("FAILED safely; diagnostic_stage="+stage+"; no Neon or LINE actions") from None

if __name__=="__main__":main()
