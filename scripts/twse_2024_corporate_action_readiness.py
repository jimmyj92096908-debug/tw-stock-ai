"""READ ONLY 2024 TWSE total-return and corporate-action readiness audit.

Compares the 894-stock official-current-listed 242-day eligible raw-price
cohort against VERIFIED corporate action events and existing adjusted bars.
Missing event records do NOT establish that an issuer never distributed
dividends. Even an 'ADJUSTED' status does not prove a complete independent
vintage-captured dividend ledger. Never train/release an investable model
on these price labels until external complete evidence is supplied.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from src.current_official_listing import CURRENT_OFFICIAL_LISTED_CTE

START = "2024-01-01"
END = "2024-12-31"
EXPECTED_TRADING_DAYS = 242
MIN_COHORT = 800
MAX_COHORT = 1000

COVERAGE_SQL = CURRENT_OFFICIAL_LISTED_CTE + """
, eligible_2024 AS (
 SELECT p.stock_id
 FROM public.daily_prices p
 JOIN official_current_listed o
   ON o.market=p.market AND o.stock_id=p.stock_id
 JOIN public.stock_master m
   ON m.market=p.market AND m.stock_id=p.stock_id
 WHERE p.market='twse'
   AND p.source='TWSE_MI_INDEX_ALLBUT0999'
   AND p.trade_date BETWEEN DATE '2024-01-01' AND DATE '2024-12-31'
   AND p.stock_id <> '1589'
   AND NOT EXISTS (
     SELECT 1 FROM public.model_stock_exclusions x
     WHERE x.market=p.market AND x.stock_id=p.stock_id
   )
 GROUP BY p.stock_id
 HAVING COUNT(*)=242
    AND BOOL_AND(COALESCE(
      p.open>0 AND p.high>=GREATEST(p.open,p.close)
      AND p.low>0 AND p.low<=LEAST(p.open,p.close)
      AND p.close>0 AND p.volume>=0,FALSE
    ))
), corp AS (
 SELECT COUNT(*)::bigint AS all_event_rows,
 COUNT(*) FILTER(WHERE c.verified)::bigint AS verified_events,
 COUNT(*) FILTER(WHERE NOT c.verified)::bigint AS unverified_events,
 COUNT(DISTINCT c.stock_id) FILTER(WHERE c.verified)::int
   AS stocks_with_verified_event
 FROM public.corporate_actions c
 JOIN eligible_2024 e ON e.stock_id=c.stock_id
 WHERE c.market='twse'
   AND c.ex_date BETWEEN DATE '2024-01-01' AND DATE '2024-12-31'
), adjusted AS (
 SELECT COUNT(*)::bigint AS total_adjusted_table_bars,
 COUNT(*) FILTER (WHERE a.adjustment_status='ADJUSTED')::bigint AS adjusted_status_bars,
 COUNT(*) FILTER (WHERE a.adjustment_status='UNADJUSTED')::bigint AS unadjusted_status_bars,
 COUNT(DISTINCT a.stock_id)::int AS stocks_with_adjusted_table_rows,
 COUNT(DISTINCT a.stock_id)
    FILTER (WHERE a.adjustment_status='ADJUSTED')::int
    AS stocks_with_adjusted_status
 FROM public.daily_adjusted_prices a
 JOIN eligible_2024 e ON e.stock_id=a.stock_id
 WHERE a.market='twse'
   AND a.trade_date BETWEEN DATE '2024-01-01' AND DATE '2024-12-31'
)
SELECT (SELECT COUNT(*)::int FROM eligible_2024) AS eligible_stocks,
       (SELECT all_event_rows FROM corp) AS all_event_rows,
       (SELECT verified_events FROM corp) AS verified_events,
       (SELECT unverified_events FROM corp) AS unverified_events,
       (SELECT stocks_with_verified_event FROM corp) AS stocks_with_verified_event,
       (SELECT total_adjusted_table_bars FROM adjusted) AS total_adjusted_table_bars,
       (SELECT adjusted_status_bars FROM adjusted) AS adjusted_status_bars,
       (SELECT unadjusted_status_bars FROM adjusted) AS unadjusted_status_bars,
       (SELECT stocks_with_adjusted_table_rows FROM adjusted)
         AS stocks_with_adjusted_table_rows,
       (SELECT stocks_with_adjusted_status FROM adjusted)
         AS stocks_with_adjusted_status
"""


def assess_counts(counts):
    if not isinstance(counts, dict):
        raise ValueError("Actual, complete read-only PostgreSQL counts required")
    names = (
        "eligible_stocks", "all_event_rows", "verified_events",
        "unverified_events", "stocks_with_verified_event",
        "total_adjusted_table_bars", "adjusted_status_bars",
        "unadjusted_status_bars", "stocks_with_adjusted_table_rows",
        "stocks_with_adjusted_status",
    )
    if any(k not in counts or type(counts[k]) is not int or counts[k] < 0
           for k in names):
        raise ValueError("Incomplete, negative or inconsistent source action audit")
    n = counts["eligible_stocks"]
    if not MIN_COHORT <= n <= MAX_COHORT:
        raise ValueError("A complete, currently listed 2024 official cohort is required")
    if (counts["all_event_rows"] !=
        counts["verified_events"] + counts["unverified_events"]):
        raise ValueError("Corporate action event statuses do not reconcile")
    if (counts["stocks_with_verified_event"] > n
        or counts["stocks_with_adjusted_status"] > n
        or counts["stocks_with_adjusted_table_rows"] > n
        or counts["stocks_with_adjusted_status"] >
           counts["stocks_with_adjusted_table_rows"]
        or counts["stocks_with_verified_event"] > counts["verified_events"]
        or counts["total_adjusted_table_bars"] > EXPECTED_TRADING_DAYS * n
        or counts["adjusted_status_bars"] +
           counts["unadjusted_status_bars"] >
           counts["total_adjusted_table_bars"]):
        raise ValueError("Adjustment and issuer cohort counts are inconsistent")

    return {
        "schema_version": 1,
        "scope": "TWSE_2024_OFFICIAL_CURRENT_LISTED_CORPORATE_ACTION_READINESS_ONLY",
        "year": 2024,
        "eligible_current_listed_242_day_cohort": n,
        "total_eligible_raw_price_bars": n * EXPECTED_TRADING_DAYS,
        "corporate_action_events_in_cohort": counts["all_event_rows"],
        "verified_corporate_action_events": counts["verified_events"],
        "unverified_corporate_action_events": counts["unverified_events"],
        "cohort_stocks_with_at_least_one_verified_action":
            counts["stocks_with_verified_event"],
        "cohort_stocks_with_adjusted_price_table_rows":
            counts["stocks_with_adjusted_table_rows"],
        "adjusted_table_rows_total": counts["total_adjusted_table_bars"],
        "rows_marked_adjusted": counts["adjusted_status_bars"],
        "rows_marked_unadjusted": counts["unadjusted_status_bars"],
        "cohort_stocks_with_at_least_one_adjusted_status":
            counts["stocks_with_adjusted_status"],
        "issuer_with_zero_record_proven_to_have_zero_dividends": False,
        "independently_complete_historical_dividend_ledger_verified": False,
        "dividend_and_split_factors_independently_verified": False,
        "source_announcement_vintage_asof_each_signal_proven": False,
        "historical_asof_issuer_membership_verified": False,
        "all_stocks_total_return_labels_validated": False,
        "research_model_allowed_to_train_on_unverified_total_return_labels": False,
        "production_live_signal_release_approved": False,
        "needs_separate_official_corporate_action_source_reconciliation": True,
        "no_production_adjusted_prices_rebuilt": True,
        "neon_database_writes": 0,
        "line_messages_sent": 0,
        "paid_upgrade_requested": False,
    }


def run_readonly(database_url, *, output=None):
    if not database_url:
        raise ValueError("Explicit read-only database URL required")
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(database_url, connect_timeout=20,
                         row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '120000ms'")
        row = conn.execute(COVERAGE_SQL).fetchone()
    report = assess_counts(dict(row) if row else None)
    result = json.dumps(report, ensure_ascii=False, indent=2,
                        allow_nan=False) + "\n"
    if len(result.encode("utf-8")) > 7000:
        raise RuntimeError("Corporate action report exceeds aggregate-only budget")
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result, encoding="utf-8")
    else:
        print(result)
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Real 2024 TWSE dividends/adjusted return coverage release BLOCKER")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    run_readonly(os.environ.get("DATABASE_URL", ""), output=args.output)


if __name__ == "__main__":
    main()
