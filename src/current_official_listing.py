"""Strict currently-official TWSE/TPEx listed issuer allowlist.

Never treat today's stock_master as proof of current exchange listing:
it is an upserted historical union. Only the newest immutable official
company-list observation, or its hash-linked correction, is eligible.
If the archive is more than 14 days old or missing, no new candidates
are returned. This rule intentionally excludes currently delisted issuers
and makes historical backtests survivor-selected and research-only.
"""
from __future__ import annotations

CURRENT_OFFICIAL_LISTED_CTE = """
WITH official_receipts AS (
 SELECT observed_at,snapshot
 FROM public.official_issuer_weekly_snapshots
 UNION ALL
 SELECT observed_at,snapshot
 FROM public.official_issuer_snapshot_corrections
),
current_receipt AS (
 SELECT observed_at,snapshot
 FROM official_receipts
 WHERE observed_at >= CURRENT_TIMESTAMP - INTERVAL '14 days'
   AND observed_at <= CURRENT_TIMESTAMP
 ORDER BY observed_at DESC
 LIMIT 1
),
official_current_listed AS (
 SELECT DISTINCT r.market,r.stock_id
 FROM current_receipt c
 CROSS JOIN LATERAL jsonb_to_recordset(c.snapshot->'records')
   AS r(market text,stock_id text)
 WHERE r.market IN ('twse','tpex')
   AND r.stock_id ~ '^[0-9]{4}$'
)
"""

# Intended only for current recommendations and owner-requested
# present-survivor research; NOT a historical point-in-time universe.
CURRENT_UNIVERSE_SELECTION = "current_official_company_list_survivors_only"
HISTORICAL_UNIVERSE_SURVIVORSHIP_FREE = False
LIVE_TRADING_APPROVED = False
