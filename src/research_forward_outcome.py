"""Research-only matured outcomes for PRECOMMITTED full model cohorts.

A model that failed old holdout CANNOT be promoted merely because later
labels exist. Entire prospective signal date must mature, including
non-selected tickers, on consistent actual t+1 and t+6 trading dates.
"""
from __future__ import annotations
from datetime import date
import math
from src.trained_factor_model import COST_BPS,TOP_FRACTION

MAX_AUDIT_COHORT=2500

# Prepared parameters: immutable model_version, signal_day, label cutoff.
# Raw positive-close sessions decide trading-day t+1 and t+6; never
# sparse adjusted-price rows or arbitrary calendar-day offsets.
FROZEN_LABEL_SQL="""
WITH frozen AS (
 SELECT f.model_version,f.signal_date,f.frozen_at,f.model_sha256,
        f.cohort_sha256,f.universe_count,f.selected_count,
        r.value->>'market' AS market,
        r.value->>'stock_id' AS stock_id,
        (r.value->>'model_rank')::integer AS model_rank,
        (r.value->>'baseline_rank')::integer AS baseline_rank
 FROM public.research_forward_frozen_cohorts f
 CROSS JOIN LATERAL jsonb_array_elements(f.roster) r(value)
 WHERE f.model_version=%s AND f.signal_date=%s
), labels AS (
 SELECT f.*,l.entry_date,l.exit_date,l.entry_adj,l.exit_adj
 FROM frozen f
 LEFT JOIN LATERAL (
  SELECT MAX(trade_date) FILTER(WHERE row_number=1) AS entry_date,
         MAX(trade_date) FILTER(WHERE row_number=6) AS exit_date,
         MAX(adjusted) FILTER(WHERE row_number=1) AS entry_adj,
         MAX(adjusted) FILTER(WHERE row_number=6) AS exit_adj
  FROM (
    SELECT p.trade_date,a.close AS adjusted,
           ROW_NUMBER() OVER(ORDER BY p.trade_date) AS row_number
    FROM (
      SELECT market,stock_id,trade_date
      FROM public.daily_prices
      WHERE market=f.market AND stock_id=f.stock_id
        AND close>0 AND trade_date>f.signal_date
        AND trade_date<=%s
      ORDER BY trade_date LIMIT 6
    ) p
    LEFT JOIN public.daily_adjusted_prices a ON
      a.market=p.market AND a.stock_id=p.stock_id
      AND a.trade_date=p.trade_date
  ) numbered
 ) l ON TRUE
), labeled AS (
 SELECT *,
 CASE WHEN entry_date IS NOT NULL AND exit_date IS NOT NULL
            AND entry_adj>0 AND exit_adj>0
            AND exit_date>entry_date
      THEN exit_adj/entry_adj-1 ELSE NULL END AS gross_return,
 CASE WHEN entry_date IS NOT NULL
      THEN (frozen_at <
        ((entry_date::timestamp+interval '13 hours 30 minutes')
         AT TIME ZONE 'Asia/Taipei'))
      ELSE FALSE END AS precommitted
 FROM labels
)
SELECT model_version,signal_date::text signal_date,MIN(frozen_at)::text frozen_at,
       MIN(model_sha256) model_sha256,MIN(cohort_sha256) cohort_sha256,
       MIN(universe_count)::int universe_count,
       MIN(selected_count)::int selected_count,
       COUNT(*)::int actual_members,
       COUNT(*) FILTER(WHERE entry_date IS NOT NULL)::int seen_entries,
       COUNT(*) FILTER(WHERE exit_date IS NOT NULL)::int seen_exits,
       COUNT(*) FILTER(WHERE gross_return IS NOT NULL AND precommitted)::int matured,
       COUNT(*) FILTER(WHERE gross_return IS NOT NULL AND NOT precommitted)::int late_precommit,
       COUNT(DISTINCT entry_date) FILTER(
          WHERE gross_return IS NOT NULL AND precommitted)::int aligned_entries,
       COUNT(DISTINCT exit_date) FILTER(
          WHERE gross_return IS NOT NULL AND precommitted)::int aligned_exits,
       MIN(entry_date) FILTER(
          WHERE gross_return IS NOT NULL AND precommitted)::text first_entry,
       MAX(entry_date) FILTER(
          WHERE gross_return IS NOT NULL AND precommitted)::text last_entry,
       MIN(exit_date) FILTER(
          WHERE gross_return IS NOT NULL AND precommitted)::text first_exit,
       MAX(exit_date) FILTER(
          WHERE gross_return IS NOT NULL AND precommitted)::text last_exit,
       COUNT(*) FILTER(WHERE model_rank<=selected_count)::int model_selection,
       COUNT(*) FILTER(WHERE baseline_rank<=selected_count)::int baseline_selection,
       COUNT(*) FILTER(
          WHERE model_rank<=selected_count AND gross_return IS NOT NULL
                AND precommitted)::int model_mature_selection,
       COUNT(*) FILTER(
          WHERE baseline_rank<=selected_count AND gross_return IS NOT NULL
                AND precommitted)::int baseline_mature_selection,
       AVG(gross_return) FILTER(WHERE precommitted)::text universe_gross,
       AVG(gross_return) FILTER(
          WHERE model_rank<=selected_count AND precommitted)::text model_gross,
       AVG(gross_return) FILTER(
          WHERE baseline_rank<=selected_count AND precommitted)::text baseline_gross
FROM labeled
GROUP BY model_version,signal_date
"""


def _int(row,name):
    v=row.get(name)
    if type(v) is not int or v<0:
        raise ValueError("Invalid frozen outcome aggregate "+name)
    return v


def _real(row,name):
    v=row.get(name)
    if v is None:
        raise ValueError("Missing complete-cohort research return "+name)
    try:
        a=float(v)
    except (ValueError,TypeError,OverflowError) as e:
        raise ValueError("Invalid research return "+name) from e
    if not math.isfinite(a) or a< -1:
        raise ValueError("Nonfinite or impossible research outcome "+name)
    return a


def assess_frozen_outcomes(row,*,cutoff):
    """Never compute partial-cohort performance or claim alpha approval."""
    if not isinstance(row,dict):
        raise ValueError("Actual bounded SQL aggregate required")
    if not isinstance(cutoff,date):
        raise ValueError("Actual date-only label cutoff required")
    signal=date.fromisoformat(row["signal_date"])
    if cutoff<=signal:
        raise ValueError("Future outcomes must follow the frozen signal date")
    total=_int(row,"universe_count")
    selected=_int(row,"selected_count")
    seen=_int(row,"actual_members")
    entry=_int(row,"seen_entries")
    exits=_int(row,"seen_exits")
    mature=_int(row,"matured")
    late=_int(row,"late_precommit")
    model_n=_int(row,"model_selection")
    baseline_n=_int(row,"baseline_selection")
    model_ready=_int(row,"model_mature_selection")
    baseline_ready=_int(row,"baseline_mature_selection")
    distinct_entry=_int(row,"aligned_entries")
    distinct_exit=_int(row,"aligned_exits")
    if not 50<=total<=MAX_AUDIT_COHORT or seen!=total:
        raise ValueError("Frozen cohort membership changed or is too small")
    if selected!=max(1,math.ceil(total*TOP_FRACTION)):
        raise ValueError("Frozen model Top-20 percent selection inconsistent")
    if min(model_n,baseline_n)!=selected or max(model_n,baseline_n)!=selected:
        raise ValueError("Frozen baseline and model selection sizes changed")
    if any(n>total for n in (entry,exits,mature,late)) or        mature+late>total or model_ready>selected or baseline_ready>selected:
        raise ValueError("Impossible forward maturity counts")
    if row.get("model_version")!="tw-factor-ridge-1":
        raise ValueError("Unrecognized frozen model source")
    for k in ("model_sha256","cohort_sha256"):
        s=row.get(k)
        if not isinstance(s,str) or len(s.strip())!=64:
            raise ValueError("Missing model and full cohort fingerprints")

    status="AWAIT_ENTRY" if entry<total else (
        "AWAIT_SIX_TRADING_SESSIONS" if exits<total else (
        "PRECOMMIT_AFTER_ENTRY_CLOSE" if late else (
        "INCOMPLETE_OFFICIAL_ADJUSTED_LABELS" if mature<total else (
        "UNALIGNED_ACTUAL_ENTRY_EXIT_DATES"
        if distinct_entry!=1 or distinct_exit!=1 or
           row["first_entry"]!=row["last_entry"] or
           row["first_exit"]!=row["last_exit"] else "FULL_COHORT_MATURE_RESEARCH_ONLY"
    ))))
    result={
        "schema_version":1,
        "model_version":row["model_version"],"signal_date":signal.isoformat(),
        "label_cutoff":cutoff.isoformat(),
        "model_sha256":row["model_sha256"].strip(),
        "cohort_sha256":row["cohort_sha256"].strip(),
        "universe_count":total,"selected_count":selected,
        "matured_members":mature,"entry_count":entry,"exit_count":exits,
        "precommitted_after_entry_close":late,
        "status":status,
        "model_net_return":None,"model_net_excess":None,
        "baseline_net_return":None,"baseline_net_excess":None,
        "portfolio_entry_date":None,"portfolio_exit_date":None,
        "corporate_action_adjustment_vintage_verified":False,
        "independently_verified_investment_alpha":False,
        "line_signal_delivery_approved":False,
        "live_trading_approved":False,
        "production_database_written":False,
    }
    if status=="FULL_COHORT_MATURE_RESEARCH_ONLY":
        if model_ready!=selected or baseline_ready!=selected:
            raise ValueError("Selected portfolios missing matured official labels")
        universe=_real(row,"universe_gross")
        model=_real(row,"model_gross")-COST_BPS/10000
        baseline=_real(row,"baseline_gross")-COST_BPS/10000
        result.update({
            "portfolio_entry_date":row["first_entry"],
            "portfolio_exit_date":row["first_exit"],
            "model_net_return":round(model,10),
            "model_net_excess":round(model-universe,10),
            "baseline_net_return":round(baseline,10),
            "baseline_net_excess":round(baseline-universe,10),
            "round_trip_cost_bps_assumed":COST_BPS,
        })
    return result
