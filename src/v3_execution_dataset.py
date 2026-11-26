"""Assemble bounded execution-label cohorts and account for missing dates.

Offline research only. Candidate rosters and session sequences must be
specified without inspecting future returns. A missing or unresolved
cohort is reported, never silently replaced with a different date.
"""
from collections import Counter
from src.v3_execution_label_cohort import execution_label_cohort
from src.v3_purged_logistic_baseline import _hash
from src.v3_probability_calibration import _day


def build_execution_dataset(*, expected_signal_dates, cohorts, label_cutoff,
                            label_settings=None):
    cutoff=_day(label_cutoff)
    if (not isinstance(expected_signal_dates,list) or not 1<=len(expected_signal_dates)<=1260
            or not isinstance(cohorts,list) or len(cohorts)>1260):
        raise ValueError("Invalid bounded dataset inputs")
    dates=[_day(d) for d in expected_signal_dates]
    if any(a>=b for a,b in zip(dates,dates[1:])) or dates[-1]>=cutoff:
        raise ValueError("Invalid expected signal dates")
    settings=dict(label_settings or {})
    allowed={"horizon_sessions","starting_cash","lot_size","commission","sell_tax",
             "slippage","stop_fraction","profit_fraction","trailing_fraction","corporate_action_mode"}
    if set(settings)-allowed:
        raise ValueError("Invalid label settings")
    by_day={}
    for c in cohorts:
        day=_day(c["signal_date"])
        if day in by_day or day not in set(dates):
            raise ValueError("Unexpected or duplicate cohort")
        if not isinstance(c["candidates"],list) or not 1<=len(c["candidates"])<=2000:
            raise ValueError("Invalid cohort candidates")
        by_day[day]=c
    if sum(len(c["candidates"]) for c in cohorts)>200000:
        raise ValueError("Candidate row cap exceeded")
    rows=[]
    audits=[]
    protocol=None
    reasons=Counter()
    for day in dates:
        c=by_day.get(day)
        audit={"signal_date":day.isoformat(),"candidate_count":0,"included_rows":0}
        if c is None:
            status="MISSING_COHORT"
        else:
            audit["candidate_count"]=len(c["candidates"])
            available=_day(c["label_available_date"])
            if available<=day:
                raise ValueError("Invalid cohort availability")
            if available>=cutoff:
                status="NOT_MATURE_AT_CUTOFF"
            else:
                if not c["sessions"] or _day(c["sessions"][0]["date"])!=day:
                    raise ValueError("Cohort signal session mismatch")
                report=execution_label_cohort(candidates=c["candidates"],sessions=c["sessions"],
                       label_available_date=c["label_available_date"],**settings)
                if protocol is not None and report["label_protocol_sha256"]!=protocol:
                    raise ValueError("Mixed execution label protocols")
                protocol=report["label_protocol_sha256"]
                status=report["status"]
                audit["closed_candidate_count"]=report["closed_candidate_count"]
                audit["candidate_status_counts"]=dict(Counter(d["status"] for d in report["diagnostics"]))
                included=report["training_rows"]
                rows.extend(included)
                audit["included_rows"]=len(included)
        audit["status"]=status
        audits.append(audit)
        reasons[status]+=1
    n=reasons["COMPLETE_SUPPLIED_COHORT"]
    return {"status":"RESEARCH_DATASET_COMPLETE_SUPPLIED_DATES" if n==len(dates) else "DATASET_COVERAGE_BLOCKED",
            "rows":rows,"rows_sha256":_hash(rows),"label_protocol_sha256":protocol,
            "label_cutoff":label_cutoff,"cohort_audit":audits,"cohort_audit_sha256":_hash(audits),
            "expected_signal_dates":len(dates),"included_signal_dates":n,
            "candidate_rows_supplied":sum(a["candidate_count"] for a in audits),
            "research_label_rows":len(rows),"approved_training_rows":0,
            "date_status_counts":dict(sorted(reasons.items())),
            "selection_bias_possible":True,"source_provenance_verified":False,
            "calendar_completeness_verified":False,"candidate_roster_verified":False,
            "model_release":"BLOCKED","trading_approved":False}
