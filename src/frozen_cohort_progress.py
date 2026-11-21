"""Bounded and read-only progress audit of REAL previously frozen model cohorts.

Unlike inspecting only the *latest* frozen day, inspect up to twelve prior
signal days with actual t+1/t+6 source labels. Do not aggregate overlapping
holding periods as independent out-of-sample evidence, and NEVER approve
real-money trading, model promotion or LINE signals.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
import math
from statistics import mean

MAX_DAYS = 12
MIN_INDEPENDENT_WINDOWS = 10
MODEL = "tw-factor-ridge-1"

DATES_SQL = """
SELECT signal_date
FROM public.research_forward_frozen_cohorts
WHERE model_version=%s
  AND signal_date<=%s::date
ORDER BY signal_date DESC
LIMIT %s::integer
"""


def _actual_day(value):
    if isinstance(value,str):
        value=date.fromisoformat(value)
    if type(value) is not date:
        raise ValueError("Real frozen signal date required")
    return value


def summarize_progress(reports, *, market_date, limit):
    latest=_actual_day(market_date)
    if type(limit) is not int or not 1<=limit<=MAX_DAYS:
        raise ValueError("Research audit limit must be 1..12")
    if not isinstance(reports,list) or len(reports)>limit:
        raise ValueError("Bounded real precommitted reports required")

    dates=set()
    hashes=set()
    status=Counter()
    mature=[]
    public=[]
    for r in reports:
        if not isinstance(r,dict):
            raise ValueError("Invalid frozen cohort research record")
        sig=_actual_day(r.get("signal_date"))
        if sig>latest or sig in dates:
            raise ValueError("Duplicate or future frozen research day")
        dates.add(sig)
        if r.get("model_version")!=MODEL or r.get("live_trading_approved") is not False or \
           r.get("line_signal_delivery_approved") is not False or \
           r.get("production_database_written") is not False:
            raise ValueError("Unexpected model permission or write on progress audit")
        mh=r.get("model_sha256")
        ch=r.get("cohort_sha256")
        if not isinstance(mh,str) or len(mh)!=64 or not isinstance(ch,str) or len(ch)!=64:
            raise ValueError("Frozen audit must preserve model and cohort fingerprints")
        hashes.add(mh)
        stage=r.get("status")
        if not isinstance(stage,str) or not stage:
            raise ValueError("Frozen model maturity status missing")
        status[stage]+=1
        public.append({
            "signal_date":sig.isoformat(),"cohort_sha256":ch,
            "status":stage,"matured_members":r.get("matured_members"),
            "universe_count":r.get("universe_count"),
        })
        if stage=="FULL_COHORT_MATURE_RESEARCH_ONLY":
            entry=_actual_day(r.get("portfolio_entry_date"))
            exit_=_actual_day(r.get("portfolio_exit_date"))
            if not sig<entry<exit_<=latest:
                raise ValueError("Invalid verified future research holding interval")
            if r.get("independently_verified_investment_alpha") is not False or \
               r.get("corporate_action_adjustment_vintage_verified") is not False:
                raise ValueError("Premature alpha or source-vintage approval")
            excess=r.get("model_net_excess")
            base=r.get("baseline_net_excess")
            if any(type(x) is not float or not math.isfinite(x) for x in (excess,base)):
                raise ValueError("Incomplete forward research net excess")
            mature.append((exit_,entry,sig,excess,base))
        else:
            for name in ("model_net_excess","baseline_net_excess","portfolio_entry_date","portfolio_exit_date"):
                if r.get(name) is not None:
                    raise ValueError("Unmatured cohort must not report portfolio returns")
    if len(hashes)>1:
        raise ValueError("Same frozen model version includes different model artifacts")

    independent=[]
    last_exit=None
    # Earliest-finishing-time first is deterministic maximum-cardinality
    # interval scheduling. Adjacent same-day entry/exit is NOT independent.
    for exit_,entry,sig,excess,base in sorted(mature):
        if last_exit is None or entry>last_exit:
            independent.append((exit_,entry,sig,excess,base))
            last_exit=exit_
    ready=len(independent)>=MIN_INDEPENDENT_WINDOWS
    public.sort(key=lambda x:x["signal_date"])
    return {
        "schema_version":1,"model_version":MODEL,
        "latest_true_market_date":latest.isoformat(),
        "audited_frozen_days":len(reports),"hard_limit":limit,
        "fixed_model_sha256":next(iter(hashes)) if hashes else None,
        "cohort_status_counts":dict(sorted(status.items())),
        "mature_full_cohorts":len(mature),
        "independent_nonoverlapping_complete_windows":len(independent),
        "minimum_independent_windows":MIN_INDEPENDENT_WINDOWS,
        "minimum_window_count_met_within_this_bounded_sample":ready,
        "exploratory_nonoverlap_model_mean_net_excess":
            round(mean(x[3] for x in independent),10) if ready else None,
        "exploratory_nonoverlap_baseline_mean_net_excess":
            round(mean(x[4] for x in independent),10) if ready else None,
        "cohorts":public,
        "market_survivorship_audited":False,
        "corporate_action_asof_vintage_audited":False,
        "pristine_future_holdout_independently_reviewed":False,
        "research_model_release_decision":"BLOCKED",
        "independently_verified_investment_alpha":False,
        "database_writes":False,
        "line_signal_delivery_approved":False,
        "live_trading_approved":False,
    }
