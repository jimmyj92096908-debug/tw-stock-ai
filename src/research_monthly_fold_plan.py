"""Pure offline predeclared monthly fold planner; not a fitted model.

Inputs are date-level full-cohort label readiness receipts. No return values,
ranks or future performance may influence date selection. Caller assertions
about source evidence are not independently authenticated here.
"""
from datetime import date
from collections import Counter

MIN_TRAIN_DATES=20
MIN_TRAIN_ROWS=100
MIN_TEST_WINDOWS=10
MIN_COHORT=5
MAX_COHORT=1990
MAX_DATES=48
KEYS={"signal_date","entry_date","exit_date","candidate_rows","complete_label_rows",
      "whole_cohort_aligned","label_kind"}


def day(v):
    if type(v) is not str:
        raise ValueError("Canonical date required")
    d=date.fromisoformat(v)
    if d.isoformat()!=v:
        raise ValueError("Canonical date required")
    return d


def plan(rows,*,label_cutoff,test_start):
    cutoff,start=map(day,(label_cutoff,test_start))
    if start>cutoff or type(rows) is not list or not 1<=len(rows)<=MAX_DATES:
        raise ValueError("Bounded date readiness input required")
    accepted=[];reasons=Counter();seen=set()
    for r in rows:
        if type(r) is not dict or set(r)!=KEYS:
            raise ValueError("Unexpected readiness schema")
        signal=day(r["signal_date"])
        n,k=r["candidate_rows"],r["complete_label_rows"]
        if (signal>cutoff or signal in seen or type(n) is not int or type(k) is not int
            or not 0<=k<=n<=MAX_COHORT or type(r["whole_cohort_aligned"]) is not bool
            or r["label_kind"]!="HYPOTHETICAL_ECONOMIC_RESEARCH_ONLY"):
            raise ValueError("Invalid readiness row")
        seen.add(signal)
        if not r["whole_cohort_aligned"] or k!=n or n<MIN_COHORT:
            reasons["incomplete_or_unaligned_cohort"]+=1
            continue
        entry,exit_=map(day,(r["entry_date"],r["exit_date"]))
        if not signal<entry<exit_:
            raise ValueError("Noncausal holding dates")
        if exit_>cutoff:
            reasons["unmatured_window"]+=1
            continue
        accepted.append((signal,entry,exit_,n))
    accepted.sort()
    folds=[];last_exit=None
    for signal,entry,exit_,n in accepted:
        if signal<start:
            continue
        train=[r for r in accepted if r[0]<signal and r[2]<signal]
        if len(train)<MIN_TRAIN_DATES or sum(r[3] for r in train)<MIN_TRAIN_ROWS:
            reasons["insufficient_mature_training"]+=1
            continue
        if last_exit is not None and signal<=last_exit:
            reasons["overlapping_test_window"]+=1
            continue
        folds.append({"signal_date":signal.isoformat(),"entry_date":entry.isoformat(),
            "exit_date":exit_.isoformat(),"test_rows":n,"training_dates":len(train),
            "training_rows":sum(r[3] for r in train),
            "training_signal_dates":[r[0].isoformat() for r in train],
            "last_mature_training_exit":max(r[2] for r in train).isoformat()})
        last_exit=exit_
    return {"scope":"OFFLINE_HYPOTHETICAL_MONTHLY_FOLD_PLAN","schema_version":1,
        "test_start":test_start,"label_cutoff":label_cutoff,"input_signal_dates":len(rows),
        "complete_mature_signal_dates":len(accepted),"test_windows":len(folds),
        "minimum_train_dates":MIN_TRAIN_DATES,"minimum_train_rows":MIN_TRAIN_ROWS,
        "minimum_test_windows":MIN_TEST_WINDOWS,"folds":folds,"exclusions":dict(sorted(reasons.items())),
        "exploratory_date_count_gate":len(folds)>=MIN_TEST_WINDOWS,
        "source_labels_authenticated":False,"model_trained":False,"alpha_verified":False,
        "production_neon_reads":0,"production_neon_writes":0,"line_messages_sent":0,
        "paid_upgrade_requested":False,"model_release":"BLOCKED"}
