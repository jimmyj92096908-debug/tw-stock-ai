"""Read-only official-listed exchange OHLCV integrity versus unpriced placeholders.

Historic source rows can have no trade/quote. Such NULL OHLC are *not*
usable factor bars and are counted separately, not silently treated as
zero prices or mislabeled as exchange-verified numerical violations.
No Neon DDL/DML, no LINE, no model publication.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from current_official_listing import CURRENT_OFFICIAL_LISTED_CTE

ALLOWED = {
    "twse": {"TWSE_MI_INDEX_ALLBUT0999", "TWSE_STOCK_DAY"},
    "tpex": {
        "TPEX_DATED_OTC_EW", "TPEX_TRADING_STOCK",
        "TPEX_TRADING_STOCK_NORMALIZED", "TPEX_DAILY_CLOSE_OPENAPI",
    },
}

PRICE_QUALITY_SQL = CURRENT_OFFICIAL_LISTED_CTE + """
SELECT p.market,p.source,
       COUNT(*)::bigint AS total_rows,
       COUNT(*) FILTER(WHERE p.open IS NULL OR p.high IS NULL
                   OR p.low IS NULL OR p.close IS NULL)::bigint AS null_ohlc_rows,
       COUNT(*) FILTER(WHERE p.volume IS NULL OR p.volume<0)::bigint AS invalid_volume_rows,
       COUNT(*) FILTER(WHERE p.open<=0 OR p.high<=0 OR p.low<=0
                   OR p.close<=0)::bigint AS nonpositive_price_rows,
       COUNT(*) FILTER(WHERE p.high<p.low
                   OR p.high<GREATEST(p.open,p.close)
                   OR p.low>LEAST(p.open,p.close))::bigint AS impossible_range_rows,
       COUNT(*) FILTER(WHERE p.open>0 AND p.high>0 AND p.low>0
                   AND p.close>0 AND p.volume>=0
                   AND p.high>=GREATEST(p.open,p.close)
                   AND p.low<=LEAST(p.open,p.close))::bigint AS usable_ohlcv_rows
FROM public.daily_prices p
INNER JOIN official_current_listed listed
 ON listed.market=p.market AND listed.stock_id=p.stock_id
WHERE p.trade_date BETWEEN %(start)s AND %(end)s
  AND p.market IN ('twse','tpex')
  AND NOT EXISTS (
      SELECT 1 FROM public.model_stock_exclusions e
      WHERE e.market=p.market AND e.stock_id=p.stock_id
  )
GROUP BY p.market,p.source ORDER BY p.market,p.source
"""


def classify(rows: list[dict]) -> dict:
    if not isinstance(rows, list) or not rows:
        raise ValueError("Missing fresh official issuer roster or actual price source")
    groups = []
    totals = {
        "price_rows": 0, "usable_ohlcv_rows": 0,
        "null_ohlc_rows": 0, "invalid_volume_rows": 0,
        "nonpositive_price_rows": 0, "impossible_range_rows": 0,
        "unknown_source_rows": 0,
    }
    for row in rows:
        market, source = row.get("market"), row.get("source")
        if market not in ALLOWED or not isinstance(source, str):
            raise ValueError("Unexpected source and exchange identity")
        values = {}
        for field in ("total_rows", "usable_ohlcv_rows", "null_ohlc_rows",
                      "invalid_volume_rows", "nonpositive_price_rows",
                      "impossible_range_rows"):
            value = row.get(field)
            if type(value) is not int or value < 0:
                raise ValueError("Unverifiable OHLCV count for " + field)
            values[field] = value
        if (values["usable_ohlcv_rows"] > values["total_rows"] or
                values["null_ohlc_rows"] > values["total_rows"] or
                values["usable_ohlcv_rows"] + values["null_ohlc_rows"] >
                values["total_rows"]):
            raise ValueError("Impossible usable vs unpriced price-row counts")
        extra = values["total_rows"] if source not in ALLOWED[market] else 0
        totals["unknown_source_rows"] += extra
        totals["price_rows"] += values["total_rows"]
        for field in values:
            if field != "total_rows":
                totals[field] += values[field]
        groups.append({"market": market, "source": source, **values,
                       "known_exchange_source": extra == 0})
    blocked = any(totals[k] > 0 for k in (
        "invalid_volume_rows", "nonpositive_price_rows",
        "impossible_range_rows", "unknown_source_rows",
    ))
    return {
        "schema_version": 1,
        "status": "BLOCKED_IMPOSSIBLE_OR_UNKNOWN_SOURCE"
                  if blocked else "PASS_UNPRICED_OLD_ROWS_EXPLICIT",
        "scope": "FRESH_OFFICIAL_CURRENT_LISTED_AND_USER_ALLOWED_ONLY",
        "source_groups": groups,
        "totals": totals,
        "null_ohlc_is_not_usable_model_history": True,
        "null_ohlc_is_not_proof_of_bad_exchange_ohlcv": True,
        "historical_asof_listing_membership_proven": False,
        "verified_five_year_completeness": False,
        "database_read_only": True,
        "database_rows_written": 0,
        "line_messages_sent": False,
        "trading_approved": False,
        "paid_upgrade_requested": False,
    }


def run(url: str, start: date, end: date) -> dict:
    if not url or type(start) is not date or type(end) is not date or start > end:
        raise ValueError("Read-only official source and bounded dates required")
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(url, connect_timeout=15, row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                cur.execute("SET LOCAL statement_timeout = '60000ms'")
                cur.execute(PRICE_QUALITY_SQL, {"start": start, "end": end})
                rows = [dict(r) for r in cur.fetchall()]
    return classify(rows)


def main() -> None:
    p = argparse.ArgumentParser(description="No-write exchange source bar quality")
    p.add_argument("--start", type=date.fromisoformat, required=True)
    p.add_argument("--end", type=date.fromisoformat, required=True)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    report = run(os.getenv("DATABASE_URL", ""), args.start, args.end)
    payload = json.dumps(report, ensure_ascii=False, indent=2,
                         allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload)
    if report["status"].startswith("BLOCKED"):
        raise SystemExit("Unknown source or impossible priced OHLCV; review required")


if __name__ == "__main__":
    main()
