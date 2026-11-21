"""Read-only actual first-observed PIT coverage for official fundamentals.

Never use a quarterly *period_end* or exchange table_date as an issuer's
publication timestamp. All three sources require real first_observed_at
at/before an explicit Taiwan research signal close cutoff.
"""
from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")

FUNDAMENTAL_ASOF_SQL = """
WITH visible_income AS (
 SELECT DISTINCT ON(market,stock_id)
   market,stock_id,period_end,first_observed_at,
   basic_eps_ytd_ntd,net_income_ytd_thousands_ntd
 FROM public.official_quarterly_income_observations
 WHERE first_observed_at<=%s::timestamptz
   AND period_end<=(%s::timestamptz AT TIME ZONE 'Asia/Taipei')::date
 ORDER BY market,stock_id,period_end DESC,
          first_observed_at DESC,payload_sha256 DESC
),visible_balance AS (
 SELECT DISTINCT ON(market,stock_id)
   market,stock_id,period_end,first_observed_at,
   assets_thousands_ntd,liabilities_thousands_ntd,equity_thousands_ntd,
   current_assets_thousands_ntd,current_liabilities_thousands_ntd,
   accounting_identity_verified
 FROM public.official_balance_sheet_observations
 WHERE first_observed_at<=%s::timestamptz
   AND period_end<=(%s::timestamptz AT TIME ZONE 'Asia/Taipei')::date
 ORDER BY market,stock_id,period_end DESC,
          first_observed_at DESC,payload_sha256 DESC
),visible_revenue AS (
 SELECT DISTINCT ON(market,stock_id)
   market,stock_id,period_end,first_observed_at,
   reported_revenue_thousands_ntd
 FROM public.official_revenue_observations
 WHERE first_observed_at<=%s::timestamptz
   AND period_end<=(%s::timestamptz AT TIME ZONE 'Asia/Taipei')::date
 ORDER BY market,stock_id,period_end DESC,
          first_observed_at DESC,payload_sha256 DESC
)
SELECT sm.market,
 COUNT(*)::int AS stock_master,
 COUNT(i.stock_id)::int AS observed_income,
 COUNT(b.stock_id)::int AS observed_balance,
 COUNT(r.stock_id)::int AS observed_revenue,
 COUNT(*) FILTER(WHERE i.stock_id IS NOT NULL
   AND b.stock_id IS NOT NULL AND i.period_end=b.period_end)::int
   AS quarterly_same_period,
 COUNT(*) FILTER(WHERE i.stock_id IS NOT NULL
   AND b.stock_id IS NOT NULL AND i.period_end=b.period_end
   AND b.accounting_identity_verified AND b.assets_thousands_ntd>0
   AND i.basic_eps_ytd_ntd IS NOT NULL
   AND i.net_income_ytd_thousands_ntd IS NOT NULL)::int
   AS safe_eps_and_balance,
 COUNT(*) FILTER(WHERE i.stock_id IS NOT NULL
   AND b.stock_id IS NOT NULL AND i.period_end=b.period_end
   AND b.accounting_identity_verified AND b.assets_thousands_ntd>0
   AND b.liabilities_thousands_ntd>=0)::int
   AS debt_to_assets_research_possible,
 COUNT(*) FILTER(WHERE b.stock_id IS NOT NULL
   AND b.accounting_identity_verified
   AND b.current_assets_thousands_ntd IS NOT NULL
   AND b.current_liabilities_thousands_ntd>0)::int
   AS current_ratio_research_possible,
 COUNT(*) FILTER(WHERE i.stock_id IS NOT NULL
   AND b.stock_id IS NOT NULL AND i.period_end=b.period_end
   AND r.stock_id IS NOT NULL)::int
   AS all_three_sources_observed,
 COUNT(*) FILTER(WHERE b.stock_id IS NOT NULL AND NOT b.accounting_identity_verified)::int
   AS accounting_identity_failures,
 COUNT(*) FILTER(WHERE b.stock_id IS NOT NULL
   AND (b.current_liabilities_thousands_ntd IS NULL
        OR b.current_liabilities_thousands_ntd=0))::int
   AS current_ratio_denominator_missing_or_zero
FROM public.stock_master sm
LEFT JOIN visible_income i ON i.market=sm.market AND i.stock_id=sm.stock_id
LEFT JOIN visible_balance b ON b.market=sm.market AND b.stock_id=sm.stock_id
LEFT JOIN visible_revenue r ON r.market=sm.market AND r.stock_id=sm.stock_id
GROUP BY sm.market
ORDER BY sm.market
"""


def actual_signal_cutoff(day, *, server_now):
    if isinstance(day, str):
        day = date.fromisoformat(day)
    if type(day) is not date:
        raise ValueError("Require real YYYY-MM-DD research signal day")
    if not isinstance(server_now, datetime) or server_now.tzinfo is None or        server_now.utcoffset() is None:
        raise ValueError("Trusted timezone-aware DB current timestamp required")
    cutoff = datetime.combine(day, time(13, 30), TAIPEI)
    if cutoff > server_now.astimezone(TAIPEI):
        raise ValueError("Cannot audit a future or not-yet-closed signal day")
    return cutoff


def audit_report(rows, *, cutoff):
    if not isinstance(cutoff,datetime) or cutoff.tzinfo is None:
        raise ValueError("Real timezone-aware as-of cutoff required")
    if not isinstance(rows,list) or len(rows)!=2:
        raise ValueError("Exactly two real stock-master markets required")
    output=[]
    markets=set()
    for raw in rows:
        market=raw.get("market")
        if market not in ("twse","tpex") or market in markets:
            raise ValueError("Unknown or duplicate official market")
        markets.add(market)
        total=raw.get("stock_master")
        if type(total) is not int or total<=0:
            raise ValueError("Real master denominator required")
        fields=(
            "observed_income","observed_balance","observed_revenue",
            "quarterly_same_period","safe_eps_and_balance",
            "debt_to_assets_research_possible","current_ratio_research_possible",
            "all_three_sources_observed","accounting_identity_failures",
            "current_ratio_denominator_missing_or_zero"
        )
        values={}
        for f in fields:
            x=raw.get(f)
            if type(x) is not int or x<0 or x>total:
                raise ValueError("Impossible source observation count "+f)
            values[f]=x
        if (values["safe_eps_and_balance"]>values["quarterly_same_period"] or
            values["quarterly_same_period"]>min(values["observed_income"],
                                                 values["observed_balance"]) or
            values["all_three_sources_observed"]>min(
                values["observed_income"],values["observed_balance"],
                values["observed_revenue"])):
            raise ValueError("Source coverage exceeds its actual eligible denominator")
        output.append({"market":market,"stock_master":total,**values})
    output.sort(key=lambda x:x["market"])
    fields=("stock_master","observed_income","observed_balance","observed_revenue",
            "quarterly_same_period","safe_eps_and_balance",
            "debt_to_assets_research_possible","current_ratio_research_possible",
            "all_three_sources_observed","accounting_identity_failures",
            "current_ratio_denominator_missing_or_zero")
    totals={f:sum(x[f] for x in output) for f in fields}
    return {
        "schema_version":1,
        "as_of_taipei":cutoff.astimezone(TAIPEI).isoformat(),
        "markets":output,"totals":totals,
        "all_master_source_joint_coverage_pct":round(
            100*totals["all_three_sources_observed"]/totals["stock_master"],2),
        "source_dates_based_on_first_observed_at":True,
        "issuer_original_publication_time_known":False,
        "cashflow_source_verified":False,
        "roe_verified":False,
        "realized_model_alpha_approved":False,
        "research_only":True,
        "database_writes":False,
        "line_signal_delivery_approved":False,
        "live_trading_approved":False,
    }
