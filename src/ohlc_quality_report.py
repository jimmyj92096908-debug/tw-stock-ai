"""Generate a read-only OHLC data-quality audit from Neon/PostgreSQL."""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def build_report(rows):
    counts = Counter()
    by_stock = defaultdict(Counter)
    markets = defaultdict(Counter)
    sources = defaultdict(set)
    first_date = None
    last_date = None

    for row in rows:
        market = row["market"]
        stock_id = row["stock_id"]
        key = (market, stock_id)
        sources[key].add(row.get("source"))

        trade_date = row["trade_date"]
        first_date = trade_date if first_date is None or trade_date < first_date else first_date
        last_date = trade_date if last_date is None or trade_date > last_date else last_date

        values = [row.get(k) for k in ("open", "high", "low", "close")]
        all_missing = all(v is None for v in values)
        partial_missing = any(v is None for v in values) and not all_missing
        volume = row.get("volume")

        if all_missing:
            if volume is not None and volume > 0:
                status = "positive_volume_no_ohlc"
            elif volume == 0:
                status = "zero_volume_no_ohlc_unconfirmed"
            else:
                status = "pending_review"
        elif partial_missing:
            status = "pending_review"
        else:
            status = "complete_ohlc"

        counts[status] += 1
        by_stock[key][status] += 1
        markets[market][status] += 1

    stock_rows = []
    for (market, stock_id), values in sorted(by_stock.items()):
        stock_rows.append({
            "market": market,
            "stock_id": stock_id,
            "stock_name": next(
                (r["stock_name"] for r in rows if r["market"] == market and r["stock_id"] == stock_id),
                "",
            ),
            "total_rows": sum(values.values()),
            "positive_volume_no_ohlc": values["positive_volume_no_ohlc"],
            "zero_volume_no_ohlc_unconfirmed": values["zero_volume_no_ohlc_unconfirmed"],
            "pending_review": values["pending_review"],
            "complete_ohlc": values["complete_ohlc"],
            "source_labels": len(sources[(market, stock_id)] - {None}),
        })

    return {
        "read_only": True,
        "database_modified": False,
        "row_count": len(rows),
        "stock_count": len({(r["market"], r["stock_id"]) for r in rows}),
        "first_date": first_date,
        "last_date": last_date,
        "totals": dict(counts),
        "by_market": {k: dict(v) for k, v in sorted(markets.items())},
        "by_stock": stock_rows,
        "source_conflicts": {
            "status": "not_determinable_from_daily_prices",
            "reason": "daily_prices stores one normalized source label per row, not parallel raw observations",
        },
        "known_official_source_discrepancies": [
            {"market": "tpex", "stock_id": "1259", "trade_date": "2026-10-05",
             "note": "Individual/monthly endpoint and bulk endpoint disagree on volume/trade counts; all checked endpoints returned missing OHLC."},
            {"market": "tpex", "stock_id": "1264", "trade_date": "2025-09-08",
             "note": "Individual/monthly endpoint and bulk endpoint disagree on volume/trade counts; all checked endpoints returned missing OHLC."},
        ],
    }


def fetch_rows(database_url):
    query = """
        SELECT p.market, p.stock_id, m.stock_name, p.trade_date,
               p.open, p.high, p.low, p.close, p.volume, p.source
        FROM daily_prices p
        JOIN stock_master m USING (market, stock_id)
        ORDER BY p.market, p.stock_id, p.trade_date
    """
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            return conn.execute(query).fetchall()


def render_markdown(report):
    totals = report["totals"]
    lines = [
        "# OHLC Data Quality Audit",
        "",
        f'- Read-only: **{report["read_only"]}**',
        f'- Database modified: **{report["database_modified"]}**',
        f'- Stocks: **{report["stock_count"]}**',
        f'- Daily rows: **{report["row_count"]}**',
        f'- Date range: **{report["first_date"]} to {report["last_date"]}**',
        "",
        "## Summary",
        "",
        "| Classification | Rows |",
        "|---|---:|",
    ]
    labels = {
        "complete_ohlc": "Complete OHLC",
        "positive_volume_no_ohlc": "Positive volume, OHLC missing",
        "zero_volume_no_ohlc_unconfirmed": "Zero volume, OHLC missing (unconfirmed)",
        "pending_review": "Pending review",
    }
    for key, label in labels.items():
        lines.append(f"| {label} | {totals.get(key, 0)} |")
    lines += [
        "",
        "## Stocks with missing or incomplete OHLC",
        "",
        "| Market | Code | Name | Positive volume / no OHLC | Zero volume / no OHLC | Pending |",
        "|---|---|---|---:|---:|---:|",
    ]
    for item in report["by_stock"]:
        missing = item["positive_volume_no_ohlc"] + item["zero_volume_no_ohlc_unconfirmed"] + item["pending_review"]
        if missing:
            lines.append(
                f'| {item["market"]} | {item["stock_id"]} | {item["stock_name"]} | '
                f'{item["positive_volume_no_ohlc"]} | {item["zero_volume_no_ohlc_unconfirmed"]} | {item["pending_review"]} |'
            )
    lines += [
        "",
        "## Source conflicts",
        "",
        "A systematic conflict count cannot be calculated from the normalized daily_prices table because it stores only one source label per row. Two known TPEx sample-date discrepancies are recorded in the JSON report. They are not treated as verified OHLC values.",
        "",
        "No rows were updated, repaired, deleted, or imputed.",
    ]
    return "\n".join(lines) + "\n"


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    rows = fetch_rows(database_url)
    report = build_report(rows)
    output = Path(os.environ.get("OHLC_AUDIT_OUTPUT", "artifacts/ohlc-quality-audit"))
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    markdown = render_markdown(report)
    (output / "summary.md").write_text(markdown, encoding="utf-8")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(markdown)
    print(markdown)


if __name__ == "__main__":
    main()
