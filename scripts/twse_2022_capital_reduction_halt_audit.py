"""2022 TWSE corporate-action suspension control for frozen-20 research.

Strictly distinguish a *legitimate non-trading session* from missing price data.
This is a bounded, research-only evidence gate, NOT cash capital-reduction
total-return adjustment, preannouncement vintage verification or model approval.

The two public 2022 issuer suspension notices are corroborated by:
2603: https://www.cna.com.tw/news/afe/202208230303.aspx
2327: https://news.cnyes.com/news/id/4972505
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, timedelta
import json
import os
from pathlib import Path

from scripts.twse_2022_aes_neon_readonly_240_panel import FROZEN_STOCKS

DATE_START = date(2022, 9, 2)
DATE_END = date(2022, 12, 30)
EXPECTED_MARKET_SESSIONS = 84
TWSE_PRIMARY = "TWSE_MI_INDEX_ALLBUT0999"
TWSE_SECONDARY = "TWSE_STOCK_DAY"
APPROVED_SOURCES = frozenset((TWSE_PRIMARY, TWSE_SECONDARY))
HALTS = {
    "2603": {
        "first": date(2022, 9, 7),
        "last": date(2022, 9, 16),
        "new_share_trading": date(2022, 9, 19),
        "notice_date": date(2022, 8, 23),
        "notice": "https://www.cna.com.tw/news/afe/202208230303.aspx",
        "action": "cash_capital_reduction_share_exchange",
    },
    "2327": {
        "first": date(2022, 10, 20),
        "last": date(2022, 10, 28),
        "new_share_trading": date(2022, 10, 31),
        "notice_date": date(2022, 10, 7),
        "notice": "https://news.cnyes.com/news/id/4972505",
        "action": "cash_capital_reduction_share_exchange",
    },
}
SQL_SESSIONS = """
SELECT DISTINCT trade_date
FROM public.daily_prices
WHERE market='twse' AND source='TWSE_MI_INDEX_ALLBUT0999'
  AND trade_date BETWEEN DATE '2022-09-02' AND DATE '2022-12-30'
ORDER BY trade_date
"""
SQL_STOCK_DAYS = """
SELECT stock_id, trade_date, source
FROM public.daily_prices
WHERE market='twse'
  AND source IN ('TWSE_MI_INDEX_ALLBUT0999','TWSE_STOCK_DAY')
  AND trade_date BETWEEN DATE '2022-09-02' AND DATE '2022-12-30'
  AND stock_id = ANY(%s::varchar[])
ORDER BY stock_id, trade_date, source
"""


def _halt_trade_dates():
    """Potential market weekdays; actual halt days intersect observed market."""
    result = set()
    for sid, notice in HALTS.items():
        if not (notice["notice_date"] < notice["first"]
                <= notice["last"] < notice["new_share_trading"]):
            raise ValueError("Unordered public capital-reduction halt notice dates")
        current = notice["first"]
        while current <= notice["last"]:
            if current.weekday() < 5:
                result.add((sid, current))
            current += timedelta(days=1)
    return result


def assess(market_dates, stock_source_rows):
    """Fails closed if any observed stock-day gap is not documented halt."""
    days = list(market_dates)
    if (len(days) != EXPECTED_MARKET_SESSIONS or
            len(set(days)) != len(days) or
            any(type(d) is not date or d < DATE_START or d > DATE_END
                or d.weekday() >= 5 for d in days)):
        raise ValueError("Expected exactly 84 unique official 2022 Sep-Dec market sessions")
    day_set = set(days)
    if min(days) != DATE_START or max(days) != DATE_END:
        raise ValueError("Official market source-calendar boundary changed")
    if len(FROZEN_STOCKS) != 20 or "1589" in FROZEN_STOCKS:
        raise ValueError("Frozen current-listed 20-stock cohort changed")

    observed = set()
    source_count = Counter()
    source_keys = set()
    count = 0
    for sid, d, source in stock_source_rows:
        count += 1
        if count > 84 * 20 * len(APPROVED_SOURCES):
            raise ValueError("Excessive official source-row count")
        if (sid not in FROZEN_STOCKS or d not in day_set or
                source not in APPROVED_SOURCES):
            raise ValueError("Unrequested stock, nonmarket date, or unofficial source")
        key = (sid, d, source)
        if key in source_keys:
            raise ValueError("Duplicate identical source stock-day key")
        source_keys.add(key)
        source_count[source] += 1
        observed.add((sid, d))

    documented_halt_days = _halt_trade_dates()
    if not documented_halt_days.issubset({
        (sid, d) for sid in HALTS for d in day_set
    }):
        raise ValueError("Published halt contains a non-observed market weekday")

    actual_missing = {
        (sid, d) for sid in FROZEN_STOCKS for d in day_set
        if (sid, d) not in observed
    }
    priced_during_halts = documented_halt_days & observed
    if priced_during_halts:
        raise ValueError("Official non-trading suspension has a price-source row")
    if actual_missing != documented_halt_days:
        raise ValueError(
            "Unexplained absent stock-days or unmatched suspension dates: "
            f"unexplained={len(actual_missing-documented_halt_days)}, "
            f"unexpected_halt_absences={len(documented_halt_days-actual_missing)}"
        )
    report_halts = [
        {
            "stock_id": sid,
            "reason": spec["action"],
            "notice_date": spec["notice_date"].isoformat(),
            "halt_from": spec["first"].isoformat(),
            "halt_through": spec["last"].isoformat(),
            "new_shares_resume": spec["new_share_trading"].isoformat(),
            "public_notice_reference": spec["notice"],
            "confirmed_official_market_nontrading_days":
                sum(1 for stock, _ in documented_halt_days if stock == sid),
        }
        for sid, spec in sorted(HALTS.items())
    ]
    return {
        "schema_version": 1,
        "scope": "TWSE_2022_84_SESSIONS_FROZEN20_CAPITAL_REDUCTION_HALT_AUDIT",
        "observed_official_market_sessions": len(day_set),
        "frozen_current_listed_research_stocks": len(FROZEN_STOCKS),
        "expected_stock_market_day_pairs": len(FROZEN_STOCKS) * len(day_set),
        "observed_distinct_stock_market_day_pairs": len(observed),
        "documented_cash_reduction_halt_stock_days": len(documented_halt_days),
        "unexplained_missing_stock_days": 0,
        "priced_days_inside_documented_halts": 0,
        "stock_source_rows_by_official_provenance": dict(sorted(source_count.items())),
        "stocks_with_all_84_market_days": sum(
            all((sid, d) in observed for d in day_set) for sid in FROZEN_STOCKS
        ),
        "documented_halts": report_halts,
        "documentary_notice_source_first_seen_audited": False,
        "actual_original_pit_publication_timestamps_verified": False,
        "corporate_action_cash_reduction_adjusted_total_returns_verified": False,
        "suspended_sessions_imputed_or_persisted": 0,
        "neon_transaction_mode": "READ_ONLY",
        "neon_writes": 0,
        "line_messages_sent": 0,
        "additional_paid_services": False,
        "live_model_release_decision": "BLOCKED",
    }


def _read_neon():
    """Bounded metadata-only queries with server-enforced read-only transaction."""
    import psycopg
    uri = os.environ.get("DATABASE_URL", "")
    if not uri.startswith(("postgres://", "postgresql://")):
        raise ValueError("DATABASE_URL must be configured locally, never printed")
    with psycopg.connect(uri, connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET LOCAL statement_timeout = '90s'")
            cur.execute(SQL_SESSIONS)
            days = [x[0] for x in cur.fetchall()]
            cur.execute(SQL_STOCK_DAYS, (list(FROZEN_STOCKS),))
            triples = [tuple(x) for x in cur.fetchall()]
            if len(triples) > 84 * 20 * len(APPROVED_SOURCES):
                raise ValueError("Unbounded source stock-day metadata")
        conn.rollback()
    return days, triples


def main():
    p = argparse.ArgumentParser(description="Neon READ ONLY 2022 capital reduction halted-day proof")
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    report = a.out.expanduser().resolve()
    if (report.exists() or not report.parent.is_dir()
            or any((p / ".git").exists() for p in report.parents)):
        raise ValueError("Private non-Git output path required; no overwrite")
    days, pairs = _read_neon()
    result = assess(days, pairs)
    with report.open("x", encoding="utf-8") as file:
        json.dump(result, file, indent=2, ensure_ascii=False, allow_nan=False)
        file.write("\n")
    print(json.dumps({
        "status": "TWSE_2022_DOCUMENTED_CAPITAL_REDUCTION_HALT_AUDIT_PASS",
        "market_sessions": result["observed_official_market_sessions"],
        "valid_price_stock_days": result["observed_distinct_stock_market_day_pairs"],
        "legitimate_halt_stock_days":
            result["documented_cash_reduction_halt_stock_days"],
        "remaining_unexplained_gaps": 0,
        "neon_writes": 0,
        "model": "BLOCKED",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
