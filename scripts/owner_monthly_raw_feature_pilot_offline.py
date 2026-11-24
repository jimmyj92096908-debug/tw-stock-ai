"""Bounded offline monthly expansion on already authenticated source groups.
No DB or network access. Quarterly feature rows are replay anchors, not a
source for invented monthly prices. The caller must authenticate inputs.
"""
from datetime import date
from scripts import twse_owner_quarterly_raw_feature_sample_readonly as q
from scripts import owner_twse_tpex_quarterly_panel_merge_offline as m

MAX_PILOT=20
CUTOFF=date(2026,11,20)


def monthly_pilot(selected,groups,bad,market_calendar,reference_calendar,quarterly_rows,*,market):
    if not 1<=len(selected)<=MAX_PILOT:
        raise ValueError("Bounded monthly pilot of at most 20 issuers")
    signals=q.monthly_signal_schedule(reference_calendar)
    anchors=[date.fromisoformat(d) for d in m.DATES]
    if not set(anchors)<=set(signals) or signals[-1]!=CUTOFF:
        raise ValueError("Previously accepted quarterly dates or cutoff changed")
    if (type(quarterly_rows) is not list or
        any(r["market"]!=market or r["stock_id"] not in selected or
            r["signal_date"] not in m.DATES for r in quarterly_rows)):
        raise ValueError("Quarterly replay rows outside selected cohort")
    report,rows=q.calculate_cohort(selected,groups,bad,market_calendar,signals,
        market=market,schedule="monthly",reference_calendar=reference_calendar)
    replay=[r for r in rows if r["signal_date"] in m.DATES]
    if not replay or replay!=quarterly_rows or m.fingerprint(replay)!=m.fingerprint(quarterly_rows):
        raise ValueError("Quarterly anchor feature replay failed")
    return {"schema_version":1,"scope":"OWNER_MONTHLY_RAW_FEATURE_PILOT_OFFLINE",
        "market":market,"candidate_stocks":len(selected),"requested_signal_dates":len(signals),
        "candidate_stock_signal_pairs":len(selected)*len(signals),
        "accepted_feature_rows":len(rows),"accepted_feature_values":len(rows)*len(m.FEATURES),
        "quarterly_anchor_rows_replayed":len(replay),"quarterly_anchor_exact":True,
        "quarterly_anchor_sha256":m.fingerprint(replay),"private_feature_rows_sha256":m.fingerprint(rows),
        "signal_date_outcomes":report["signal_date_outcomes"],"feature_version":m.VERSION,
        "feature_names":m.FEATURES,"prefix_only_feature_computation":True,
        "official_market_calendar_independently_proven":False,"current_roster_not_historical_pit":True,
        "forward_labels_created":False,"corporate_actions_adjusted":False,"model_trained":False,
        "production_neon_reads":0,"production_neon_writes":0,"line_messages_sent":0,
        "paid_upgrade_requested":False,"model_release":"BLOCKED"},rows


def schedule_budget():
    # Dec 2022 through Nov 2026 inclusive. Maxima, not observed coverage.
    months=48
    return {"scope":"MONTHLY_SCHEDULE_CAPACITY_NOT_DATA_EVIDENCE",
        "monthly_candidate_dates":months,"maximum_potential_mature_dates":months-1,
        "quarterly_candidate_dates":17,"minimum_existing_ridge_train_dates":20,
        "minimum_exploratory_test_windows":10,"candidate_dates_after_minimum_training":months-1-20,
        "full_dual_market_candidate_pairs":1990*months,
        "full_dual_market_candidate_feature_values":1990*months*len(m.FEATURES),
        "new_monthly_features_verified":False,"model_release":"BLOCKED"}


if __name__=="__main__":
    import json
    print(json.dumps(schedule_budget(),allow_nan=False))
