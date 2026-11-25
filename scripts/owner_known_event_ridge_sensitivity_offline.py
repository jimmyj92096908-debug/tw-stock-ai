"""Owner-only known-event Ridge sensitivity, never a total-return label ledger."""
import argparse
from datetime import date
from fractions import Fraction
import json
from scripts import owner_raw_price_ridge_diagnostic_offline as raw
from scripts import owner_known_action_event_sensitivity_offline as event

ridge=raw.ridge

def compare(stocks,features,late,witness):
    baseline,paths=raw.evaluate(stocks,features,late)
    data,_,_=raw.build_paths(stocks,features,late)
    by_key={(p["signal_date"],p["stock_id"]):p for p in paths}
    corrections={}
    seen=set()
    for e in witness["events"]:
        key=e["signal_date"],e["stock_id"]
        if key in seen or key not in by_key:
            raise ValueError("Unexpected or duplicate event path")
        seen.add(key)
        p=by_key[key]
        ix=p["sessions"].index(e["event_date"])
        if e["entry_close_excluded"] != (ix==0):
            raise ValueError("Entry entitlement mismatch")
        if ix==0:continue
        entry=Fraction(p["raw_closes"][0])
        sale=Fraction(p["raw_closes"][-1])*Fraction(e["share_multiplier_candidate"])/entry
        cash=Fraction(e["cash_per_old_share_candidate"])/entry
        if sale<=0 or cash<0 or not 0<sale+cash<=11:
            raise ValueError("Invalid event economics")
        corrections[key]=(float(sale),float(cash))
    if len(corrections)!=witness["in_holding_events"]:
        raise ValueError("Unexpected correction count")
    def economics(d,m):
        return corrections.get((d.isoformat(),m[0]),(m[3],0.0))
    lookup={d:(entry,exit_,members) for d,entry,exit_,members in data}
    folds=[]
    for f in baseline["folds"]:
        d=date.fromisoformat(f["signal_date"])
        entry,exit_,members=lookup[d]
        train=[(dt,m) for dt,_,ex,mm in data if dt<d and ex<d for m in mm]
        if len(train)!=f["training_rows"]:raise ValueError("Training cohort drift")
        x=[m[1] for _,m in train]
        def fit(adjusted):
            y=[sum(economics(dt,m))-1 if adjusted and (dt.isoformat(),m[0]) in corrections else m[2] for dt,m in train]
            mu,sd,w,ybar=ridge.fit(x,y)
            pred=(ridge.np.asarray([m[1] for m in members])-mu)/sd@w+ybar
            if not ridge.np.all(ridge.np.isfinite(pred)):raise ValueError("Invalid predictions")
            best=members[min(range(len(members)),key=lambda i:(-float(pred[i]),members[i][0]))]
            return best,ridge.fingerprint([mu.tolist(),sd.tolist(),w.tolist(),ybar])
        a,ha=fit(False);z,hz=fit(True)
        if ha!=f["fitted_state_sha256"] or ridge.fingerprint(a[0])!=f["selection_sha256"]:
            raise ValueError("Raw model parity failure")
        cases=[]
        for i,slip in enumerate(ridge.SLIPPAGE_BPS):
            raw_a=ridge.net_return(a[3],0,slip)
            raw_eq=sum(ridge.net_return(m[3],0,slip) for m in members)/len(members)
            if abs(raw_a-raw_eq-f["cost_scenarios"][i]["raw_net_excess"])>1e-12:
                raise ValueError("Raw cost parity failure")
            def net(m):
                sale,cash=economics(d,m)
                return ridge.net_return(sale,cash,slip)
            eq=sum(net(m) for m in members)/len(members)
            cases.append({"slippage_each_way_bps":slip,
                "raw_fit_raw_eval_excess":raw_a-raw_eq,
                "raw_fit_known_event_eval_excess":net(a)-eq,
                "known_event_fit_eval_excess":net(z)-eq})
        folds.append({"signal_date":d.isoformat(),"entry_date":entry.isoformat(),"exit_date":exit_.isoformat(),
            "training_rows":len(train),"last_mature_training_exit":f["last_mature_training_exit"],
            "known_event_training_rows":sum((dt.isoformat(),m[0]) in corrections for dt,m in train),
            "selection_changed":a[0]!=z[0],"raw_fit_sha256":ha,"known_event_fit_sha256":hz,
            "cost_scenarios":cases})
    result={"scope":"OWNER_KNOWN_EVENT_RIDGE_SENSITIVITY_NOT_TOTAL_RETURN",
        "evaluated_test_windows":len(folds),"raw_path_rows":len(paths),"known_event_corrected_paths":len(corrections),
        "unknown_event_paths_not_certified":True,"approved_total_return_labels":0,
        "historical_publication_vintage_verified":False,"official_calendar_independently_verified":False,
        "current_roster_not_historical_pit":True,"source_selection_conditioned_on_later_availability":True,
        "stock_entitlement_marked_at_exit_not_actual_sale":True,"alpha_verified":False,
        "corporate_action_coverage_verified":False,"production_model_trained":False,
        "production_weights_updated":False,"production_neon_reads":0,"production_neon_writes":0,
        "line_messages_sent":0,"paid_upgrade_requested":False,"model_release":"BLOCKED",
        "folds":folds}
    if folds:
        result["selection_changed_windows"]=sum(f["selection_changed"] for f in folds)
        result["mean_worst_cost_excess"]={k:sum(f["cost_scenarios"][-1][k] for f in folds)/len(folds)
            for k in ("raw_fit_raw_eval_excess","raw_fit_known_event_eval_excess","known_event_fit_eval_excess")}
    return result,baseline,paths

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("panel","monthly","cache-dir","action-cache-dir","raw-research","out"):
        p.add_argument("--"+key,required=True)
    a=p.parse_args();b=raw.b
    try:
        panel,_=b.m.read_panel(b.m.private_path(a.panel,existing=True))
        stocks=b.five.select(b.chip.verify_input(panel))
        monthly,_=b.m.read_panel(b.m.private_path(a.monthly,existing=True))
        features=monthly["private_feature_rows"]
        if (b.m.fingerprint(list(stocks))!=b.SAMPLE_HASH or monthly["sample_stock_ids"]!=list(stocks)
            or b.m.fingerprint(features)!=raw.FEATURE_HASH or len(features)!=228):
            raise ValueError("Frozen features changed")
        late,h=b.load_late(stocks,a.cache_dir)
        if h!=raw.LATE_HASH:raise ValueError("Frozen late cache changed")
        frozen,_=b.m.read_panel(b.m.private_path(a.raw_research,existing=True))
        baseline,paths=raw.evaluate(stocks,features,late)
        if paths!=frozen["private_action_window_paths"]:raise ValueError("Path parity failure")
        expected=dict(baseline,feature_rows_sha256=raw.FEATURE_HASH,late_response_hashes_sha256=h,
                      private_action_window_paths_sha256=b.m.fingerprint(paths))
        if expected!=frozen["summary"]:raise ValueError("Baseline parity failure")
        witness=event.verify(paths,a.action_cache_dir)
        result,_,_=compare(stocks,features,late,witness)
        if result["evaluated_test_windows"]!=14 or result["raw_path_rows"]!=175 or result["known_event_corrected_paths"]!=2:
            raise ValueError("Frozen research scope changed")
        result["private_action_window_paths_sha256"]=b.m.fingerprint(paths)
        out=b.m.private_path(a.out,existing=False)
        with out.open("x",encoding="utf-8") as f:
            json.dump(result,f,indent=2,allow_nan=False);f.write("\n")
        print(json.dumps(result,allow_nan=False))
    except Exception:
        raise SystemExit("FAILED safely; sensitivity not approved; no Neon or LINE actions") from None

if __name__=="__main__":main()
