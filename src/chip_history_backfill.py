"""Bounded, opt-in TWSE chip history repair for the tracked research cohort.

Default: aggregate gap preview only, no HTTP requests and NO writes.
Apply: --apply PLUS CHIP_HISTORY_WRITE_ENABLED=yes and a separate operator approval.
TWSE T86 and MI_MARGN have date-addressed queries. TPEx daily OpenAPI is a
latest-only snapshot and MUST NOT be used to manufacture historical records.
"""
from __future__ import annotations

import argparse
import os
from datetime import date

import psycopg
from psycopg.rows import dict_row

try:  # Support both 'python src/...' and importing as 'src....' in tests.
    from . import institutional_data, margin_data
except ImportError:
    import institutional_data
    import margin_data

TRACKED_TWSE = frozenset(institutional_data.STOCKS["twse"])
MAX_TRADING_DAYS = 30

STOCK_DATES_SQL = """
SELECT trade_date, EXISTS (
    SELECT 1 FROM public.institutional_flows i
    WHERE i.market='twse' AND i.stock_id=%s AND i.trade_date=p.trade_date
) AS has_institutional, EXISTS (
    SELECT 1 FROM public.margin_short m
    WHERE m.market='twse' AND m.stock_id=%s AND m.trade_date=p.trade_date
) AS has_margin
FROM (
    SELECT DISTINCT trade_date
    FROM public.daily_prices
    WHERE market='twse' AND stock_id=%s AND close IS NOT NULL
    ORDER BY trade_date DESC LIMIT %s
) p
ORDER BY trade_date DESC
"""

INSERT_INSTITUTIONAL = """
INSERT INTO public.institutional_flows
(market,stock_id,trade_date,foreign_buy,foreign_sell,foreign_net,
 trust_buy,trust_sell,trust_net,dealer_buy,dealer_sell,dealer_net,
 total_net,source,retrieved_at)
VALUES
(%(market)s,%(stock_id)s,%(trade_date)s,%(foreign_buy)s,%(foreign_sell)s,%(foreign_net)s,
 %(trust_buy)s,%(trust_sell)s,%(trust_net)s,%(dealer_buy)s,%(dealer_sell)s,%(dealer_net)s,
 %(total_net)s,'TWSE_T86',now())
ON CONFLICT (market,stock_id,trade_date) DO NOTHING
"""

INSERT_MARGIN = """
INSERT INTO public.margin_short
(market,stock_id,trade_date,margin_buy,margin_sell,margin_repayment,
 margin_balance,short_sell,short_buyback,short_repayment,short_balance,
 margin_quota,short_quota,source,retrieved_at)
VALUES
(%(market)s,%(stock_id)s,%(trade_date)s,%(margin_buy)s,%(margin_sell)s,%(margin_repayment)s,
 %(margin_balance)s,%(short_sell)s,%(short_buyback)s,%(short_repayment)s,%(short_balance)s,
 %(margin_quota)s,%(short_quota)s,'TWSE_MI_MARGN',now())
ON CONFLICT (market,stock_id,trade_date) DO NOTHING
"""


def validate_options(stock_id: str, days: int, apply: bool) -> None:
    if stock_id not in TRACKED_TWSE:
        raise ValueError("Only explicitly tracked TWSE symbols are supported; TPEx has no dated-backfill endpoint")
    if not isinstance(days, int) or not 1 <= days <= MAX_TRADING_DAYS:
        raise ValueError("Trading-day lookback must be within 1..30")
    if apply and os.environ.get("CHIP_HISTORY_WRITE_ENABLED") != "yes":
        raise PermissionError("Apply requires CHIP_HISTORY_WRITE_ENABLED=yes and explicit operator approval")


def plan_gaps(conn, stock_id: str, days: int) -> list[dict]:
    """Return actual saved price-session dates, never guessed calendar trading dates."""
    with conn.cursor() as cur:
        cur.execute(STOCK_DATES_SQL, (stock_id, stock_id, stock_id, days))
        rows = cur.fetchall()
    return [
        {"date": row["trade_date"],
         "institutional_missing": not row["has_institutional"],
         "margin_missing": not row["has_margin"]}
        for row in rows
    ]


def _official_record(market: str, stock_id: str, requested: date, records: list[dict]) -> dict:
    selected = [r for r in records
                if r.get("market") == market and r.get("stock_id") == stock_id]
    if len(selected) != 1:
        raise RuntimeError(
            f"Official dated feed must contain exactly one row for {market} {stock_id} on {requested}"
        )
    row = selected[0]
    if str(row.get("trade_date")) != requested.isoformat():
        raise RuntimeError("Official parsed trade date differs from requested trading session")
    return row


def fetch_missing_twse(stock_id: str, gaps: list[dict], *, session=None) -> tuple[list[dict], list[dict]]:
    """Preflight ALL official dated feeds before performing a single DB write."""
    session = session or institutional_data._session()
    inst_rows, margin_rows = [], []
    for gap in gaps:
        day = gap["date"]
        iso = day.isoformat()
        ymd = iso.replace("-", "")
        if gap["institutional_missing"]:
            response = session.get(
                institutional_data.TWSE_URL,
                params={"date": ymd, "selectType": "ALL", "response": "json"},
                headers=institutional_data.HEADERS, timeout=(15, 60),
            )
            response.raise_for_status()
            payload = response.json()
            # T86 provides an official date. Without a matching date, never
            # relabel a latest snapshot as a historical observation.
            actual = institutional_data.ad_date(payload.get("date"))
            if actual != iso:
                raise RuntimeError(f"TWSE T86 date not proven for {iso}; refusing history repair")
            record = _official_record("twse", stock_id, day,
                                      institutional_data.parse_twse(payload, iso))
            inst_rows.append(record)
        if gap["margin_missing"]:
            response = session.get(
                margin_data.TWSE_URL,
                params={"date": ymd, "selectType": "STOCK", "response": "json"},
                headers=margin_data.HEADERS, timeout=(15, 60),
            )
            response.raise_for_status()
            record = _official_record("twse", stock_id, day,
                                      margin_data.parse_twse(response.json(), iso))
            margin_rows.append(record)
    return inst_rows, margin_rows


def apply_missing(conn, inst_rows: list[dict], margin_rows: list[dict]) -> tuple[int, int]:
    """Insert-only: official source rows with an existing PK are never overwritten."""
    with conn.transaction():
        with conn.cursor() as cur:
            inserted_inst = 0
            inserted_margin = 0
            for row in inst_rows:
                cur.execute(INSERT_INSTITUTIONAL, row)
                inserted_inst += cur.rowcount
            for row in margin_rows:
                cur.execute(INSERT_MARGIN, row)
                inserted_margin += cur.rowcount
    return inserted_inst, inserted_margin


def run(database_url: str, stock_id: str = "2330", days: int = 25,
        *, apply: bool = False, session=None) -> dict:
    validate_options(stock_id, days, apply)
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=20) as conn:
        gaps = plan_gaps(conn, stock_id, days)
        missing_inst = sum(x["institutional_missing"] for x in gaps)
        missing_margin = sum(x["margin_missing"] for x in gaps)
        result = {"stock_id": stock_id, "actual_price_sessions": len(gaps),
                  "missing_institutional": missing_inst, "missing_margin": missing_margin,
                  "inserted_institutional": 0, "inserted_margin": 0,
                  "mode": "apply" if apply else "preview"}
        if not apply:
            return result
        if not gaps:
            raise RuntimeError("No saved real-price sessions; refusing history repair")
        inst_rows, margin_rows = fetch_missing_twse(stock_id, gaps, session=session)
        result["inserted_institutional"], result["inserted_margin"] = apply_missing(
            conn, inst_rows, margin_rows)
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview or explicitly backfill actual TWSE chip sessions")
    parser.add_argument("--stock", choices=sorted(TRACKED_TWSE), default="2330")
    parser.add_argument("--days", type=int, default=25)
    parser.add_argument("--apply", action="store_true", help="Requires separately authorized DB write gate")
    args = parser.parse_args()
    result = run(os.environ.get("DATABASE_URL", ""),
                 stock_id=args.stock, days=args.days, apply=args.apply)
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
