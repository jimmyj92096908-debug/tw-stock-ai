"""Read-only overlap audit; never convert raw closes into approved labels."""
import argparse
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import math
from pathlib import Path
import re

def digest(rows):
    return sha256(json.dumps(rows,sort_keys=True,separators=(",",":"),
                             ensure_ascii=True,allow_nan=False).encode("utf-8")).hexdigest()

def key(row):
    m=row["market"].lower()
    s=row["stock_id"]
    d=row["signal_date"]
    if m not in ("twse","tpex") or not isinstance(s,str) or not re.fullmatch("[0-9]{4,6}",s) or date.fromisoformat(d).isoformat()!=d:
        raise ValueError("Invalid historical key")
    return m,s,d

def positive_close(value):
    # Some historical producers serialize Decimal prices as JSON strings.
    # Do not accept booleans, formatted currency, whitespace or nonfinite data.
    if type(value) in (int,float):
        return math.isfinite(value) and value>0
    if isinstance(value,str) and len(value)<=64 and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?",value):
        try:
            n=Decimal(value)
            return n.is_finite() and n>0
        except InvalidOperation:
            return False
    return False

def canonical_day(value):
    try:
        return isinstance(value,str) and date.fromisoformat(value).isoformat()==value
    except ValueError:
        return False

def audit_overlap(joined,actions):
    jm=joined["summary"]
    rows=joined["retrospective_joined_factors"]
    am=actions["summary"]
    paths=actions["private_matched_rows"]
    if (jm["status"]!="RETROSPECTIVE_JOIN_RESEARCH_ONLY" or
        jm["model_release"]!="BLOCKED" or jm["approved_training_feature_rows"]!=0 or
        len(rows)!=jm["matched_rows"] or digest(rows)!=jm["matched_rows_sha256"] or
        not 1<=len(rows)<=200000):
        raise ValueError("Joined factor manifest mismatch")
    if (am["model_release"]!="BLOCKED" or am["approved_total_return_labels"]!=0 or
        am["corporate_action_coverage_verified"] is not False or
        len(paths)!=am["matched_raw_feature_label_rows"] or
        not 1<=len(paths)<=200000):
        raise ValueError("Action candidate manifest mismatch")
    names=jm["feature_names"]
    if len(names)!=15 or len(set(names))!=15 or names[-3:]!=[
        "institutional_net_shares_20","institutional_turnover_shares_20","institutional_imbalance_20"]:
        raise ValueError("Unexpected factor schema")
    index={}
    for r in rows:
        k=key(r)
        if (k in index or k[0]!="twse" or k[1] in ("1589","1808") or
            r["historical_reconstruction_only"] is not True or
            r["strict_point_in_time_verified"] is not False or
            r["approved_training_feature"] is not False or set(r["features"])!=set(names)):
            raise ValueError("Invalid joined factor row")
        index[k]=r
    seen=set()
    matched=Counter()
    parity=Counter()
    close_shapes=Counter()
    chronology=Counter()
    joint_valid=Counter()
    date_starts=Counter()
    close_types=Counter()
    session_types=Counter()
    close_lengths=Counter()
    session_lengths=Counter()
    string_price_paths=0
    return_checks=Counter()
    cost_checks={bps:Counter() for bps in (0,10,25)}
    gross_return_sum=Decimal(0)
    cost_return_sums={bps:Decimal(0) for bps in cost_checks}
    for p in paths:
        k=key(p)
        if k in seen:
            raise ValueError("Duplicate raw path key")
        seen.add(k)
        if p["approved_total_return"] is not False or p["corporate_action_coverage_verified"] is not False:
            raise ValueError("Unexpected label approval")
        if k not in index:
            continue
        matched[k[2]]+=1
        v=p["feature_vector"]
        if isinstance(v,list) and len(v)==12 and v==[index[k]["features"][n] for n in names[:12]]:
            parity[k[2]]+=1
        sessions=p["sessions"]
        closes=p["raw_closes"]

        close_lengths[str(len(closes)) if isinstance(closes,list) else "not_array"]+=1
        session_lengths[str(len(sessions)) if isinstance(sessions,list) else "not_array"]+=1
        if isinstance(closes,list):
            close_types.update(type(x).__name__ for x in closes)
        if isinstance(sessions,list):
            session_types.update(type(x).__name__ for x in sessions)
        valid_prices=isinstance(closes,list) and len(closes)==6 and all(positive_close(x) for x in closes)
        if valid_prices:
            close_shapes[k[2]]+=1
            string_price_paths+=int(any(isinstance(x,str) for x in closes))
        ordered=isinstance(sessions,list) and len(sessions)==6 and all(canonical_day(x) for x in sessions) and all(a<b for a,b in zip(sessions,sessions[1:]))
        if ordered:
            date_starts["after_signal" if sessions[0]>k[2] else ("at_signal" if sessions[0]==k[2] else "before_signal")]+=1
            if sessions[0]>k[2]:
                chronology[k[2]]+=1
                if valid_prices:
                    joint_valid[k[2]]+=1
                    # Close-to-close proxy only, not executable stop/target labels.
                    entry,exit_=Decimal(str(closes[0])),Decimal(str(closes[-1]))
                    gross=exit_/entry-1
                    try:
                        value=p.get("raw_gross_return")
                        if type(value) not in (str,int,float) or len(str(value))>80:
                            raise ValueError("Invalid reported return")
                        stated=Decimal(str(value))
                        if not stated.is_finite():
                            raise ValueError("Nonfinite return")
                        if abs(gross-stated)<=Decimal("0.00000001"):
                            return_checks["recomputed_match"]+=1
                        else:
                            return_checks["recomputed_mismatch"]+=1
                    except (InvalidOperation,ValueError):
                        return_checks["missing_or_invalid_reported_return"]+=1
                    gross_return_sum+=gross
                    for bps,counts in cost_checks.items():
                        slip=Decimal(bps)/10000
                        net=exit_*(1-slip)*(1-Decimal("0.001425")-Decimal("0.003"))/(entry*(1+slip)*(1+Decimal("0.001425")))-1
                        counts["rows"]+=1
                        counts["positive"]+=int(net>0)
                        cost_return_sums[bps]+=net
    expected=Counter(k[2] for k in index)
    return dict(status="RAW_PATH_OVERLAP_AUDITED_RESEARCH_ONLY",
                joined_rows=len(rows),joined_signal_dates=len(expected),
                action_candidate_rows=len(paths),exact_key_overlap_rows=sum(matched.values()),
                matching_technical_vectors=sum(parity.values()),
                six_positive_closes=sum(close_shapes.values()),
                strictly_post_signal_ordered_paths=sum(chronology.values()),
                overlap_signal_dates=len(matched),
                raw_close_element_types=dict(close_types),session_element_types=dict(session_types),
                raw_close_array_lengths=dict(close_lengths),session_array_lengths=dict(session_lengths),
                positive_decimal_string_paths=string_price_paths,
                ordered_session_start_relation=dict(date_starts),
                jointly_valid_post_signal_price_paths=sum(joint_valid.values()),
                no_raw_path_rows=len(rows)-sum(matched.values()),
                raw_gross_return_reconciliation=dict(return_checks),
                close_to_close_proxy_mean_gross=float(gross_return_sum/sum(joint_valid.values())) if joint_valid else None,
                close_to_close_cost_sensitivity=[
                    dict(slippage_each_way_bps=bps,rows=counts["rows"],
                         positive_rows=counts["positive"],
                         positive_fraction=counts["positive"]/counts["rows"] if counts["rows"] else None,
                         mean_net_return=float(cost_return_sums[bps]/counts["rows"]) if counts["rows"] else None)
                    for bps,counts in cost_checks.items()],
                proxy_cost_assumptions=dict(commission_each_way=.001425,sell_tax=.003,
                    minimum_commission_applied=False,corporate_actions_applied=False,
                    liquidity_or_fill_constraints_applied=False),
                proxy_statistics_not_model_performance=True,
                coverage_by_signal_date=[dict(signal_date=d,joined_rows=expected[d],
                    overlap_rows=matched[d],vector_parity_rows=parity[d],
                    six_close_rows=close_shapes[d],ordered_post_signal_rows=chronology[d]) for d in sorted(expected)],
                joined_digest_verified=True,action_array_digest_computed=digest(paths),
                action_declared_digest=am["matched_panel_sha256"],
                action_canonical_digest_matches=digest(paths)==am["matched_panel_sha256"],
                original_action_digest_recipe_verified=False,
                raw_close_path_is_execution_label=False,
                approved_training_feature_rows=0,approved_total_return_labels=0,
                v3_model_trained=False,model_release="BLOCKED",
                production_neon_reads=0,production_neon_writes=0,line_messages_sent=0)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--joined",type=Path,required=True)
    p.add_argument("--actions",type=Path,required=True)
    a=p.parse_args()
    def load(path):
        if path.stat().st_size>128*1024*1024:
            raise ValueError("Input too large")
        return json.loads(path.read_text(encoding="utf-8-sig"))
    print(json.dumps(audit_overlap(load(a.joined),load(a.actions)),indent=2,allow_nan=False))

if __name__=="__main__":
    main()
