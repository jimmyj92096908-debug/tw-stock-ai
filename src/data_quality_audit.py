"""Read-only audit of Taiwan stock daily-price coverage and integrity."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "data" / "quality" / "data_quality_report.json"
SUMMARY_PATH = os.environ.get("GITHUB_STEP_SUMMARY")


QUERIES = {
    "market_coverage": """
        SELECT sm.market, COUNT(*) AS master_symbols,
               COUNT(dp.stock_id) AS symbols_with_prices,
               ROUND(100.0 * COUNT(dp.stock_id) / NULLIF(COUNT(*), 0), 2) AS coverage_pct
        FROM stock_master sm
        LEFT JOIN (SELECT DISTINCT market, stock_id FROM daily_prices) dp
          ON dp.market = sm.market AND dp.stock_id = sm.stock_id
        GROUP BY sm.market ORDER BY sm.market
    """,
    "price_integrity": """
        SELECT market, COUNT(*) AS rows,
          COUNT(*) FILTER (WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL) AS missing_ohlc,
          COUNT(*) FILTER (WHERE volume IS NULL) AS missing_volume,
          COUNT(*) FILTER (WHERE open <= 0 OR high <= 0 OR low <= 0 OR close <= 0) AS nonpositive_prices,
          COUNT(*) FILTER (WHERE high < low OR high < open OR high < close OR low > open OR low > close) AS invalid_ohlc,
          COUNT(*) FILTER (WHERE volume < 0) AS negative_volume,
          MIN(trade_date) AS first_date, MAX(trade_date) AS latest_date
        FROM daily_prices GROUP BY market ORDER BY market
    """,
    "latest_date_coverage": """
        WITH latest AS (SELECT MAX(trade_date) AS d FROM daily_prices)
        SELECT latest.d AS latest_trade_date, dp.market,
               COUNT(DISTINCT dp.stock_id) AS symbols_on_latest_date
        FROM latest JOIN daily_prices dp ON dp.trade_date = latest.d
        GROUP BY latest.d, dp.market ORDER BY dp.market
    """,
    "history_coverage": """
        SELECT market,
          COUNT(*) FILTER (WHERE first_date <= DATE '2021-01-01') AS five_year_symbols,
          COUNT(*) AS symbols_with_data,
          MIN(first_date) AS earliest_start
        FROM (SELECT market, stock_id, MIN(trade_date) AS first_date
              FROM daily_prices GROUP BY market, stock_id) s
        GROUP BY market ORDER BY market
    """,
    "duplicate_keys": """
        SELECT market, stock_id, trade_date, COUNT(*) AS duplicate_count
        FROM daily_prices GROUP BY market, stock_id, trade_date
        HAVING COUNT(*) > 1 ORDER BY duplicate_count DESC LIMIT 50
    """,
    "stale_symbols": """
        SELECT market, stock_id, MAX(trade_date) AS last_trade_date
        FROM daily_prices
        GROUP BY market, stock_id
        HAVING MAX(trade_date) < CURRENT_DATE - INTERVAL '10 days'
        ORDER BY last_trade_date LIMIT 100
    """,
}


def fetch_report(conn: Any) -> dict[str, Any]:
    report: dict[str, Any] = {}
    with conn.cursor() as cur:
        for key, sql in QUERIES.items():
            cur.execute(sql)
            report[key] = cur.fetchall()
    return report


def summarize(report: dict[str, Any]) -> dict[str, Any]:
    coverage = report.get("market_coverage", [])
    total_master = sum(int(row["master_symbols"]) for row in coverage)
    total_covered = sum(int(row["symbols_with_prices"]) for row in coverage)
    integrity = report.get("price_integrity", [])
    bad_rows = sum(
        int(row["missing_ohlc"]) + int(row["missing_volume"]) +
        int(row["nonpositive_prices"]) + int(row["invalid_ohlc"]) +
        int(row["negative_volume"]) for row in integrity
    )
    duplicates = report.get("duplicate_keys", [])
    stale = report.get("stale_symbols", [])
    history = report.get("history_coverage", [])
    five_year_count = sum(int(row["five_year_symbols"]) for row in history)
    return {
        "master_symbols": total_master,
        "symbols_with_prices": total_covered,
        "coverage_pct": round(total_covered * 100 / total_master, 2) if total_master else 0.0,
        "bad_price_rows_counted": bad_rows,
        "duplicate_key_groups": len(duplicates),
        "stale_symbols_listed": len(stale),
        "symbols_with_five_year_history": five_year_count,
        "markets": coverage,
        "integrity": integrity,
        "latest_date_coverage": report.get("latest_date_coverage", []),
        "history": history,
        "duplicate_examples": duplicates,
        "stale_examples": stale,
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "## Taiwan stock market data quality audit",
        "",
        f"- Stock master symbols: **{summary['master_symbols']}**",
        f"- Symbols with daily bars: **{summary['symbols_with_prices']}**",
        f"- Universe coverage: **{summary['coverage_pct']}%**",
        f"- Symbols with >= 5-year history (start <= 2021-01-01): **{summary['symbols_with_five_year_history']}**",
        f"- Integrity issue counts (may overlap): **{summary['bad_price_rows_counted']}**",
        f"- Duplicate (market, symbol, date) groups: **{summary['duplicate_key_groups']}**",
        f"- Stale symbol rows listed (>10 calendar days): **{summary['stale_symbols_listed']}**",
        "",
        "### Coverage by market",
        "| Market | Master | Covered | Coverage |",
        "|---|---:|---:|---:|",
    ]
    for row in summary["markets"]:
        lines.append(f"| {row['market']} | {row['master_symbols']} | {row['symbols_with_prices']} | {row['coverage_pct']}% |")
    lines += ["", "### Latest date coverage", "| Market | Latest trade date | Symbols |", "|---|---|---:|"]
    for row in summary["latest_date_coverage"]:
        lines.append(f"| {row['market']} | {row['latest_trade_date']} | {row['symbols_on_latest_date']} |")
    lines += ["", "### Integrity by market", "| Market | Rows | Missing OHLC | Missing volume | Nonpositive price | Invalid OHLC | Negative volume |", "|---|---:|---:|---:|---:|---:|---:|"]
    for row in summary["integrity"]:
        lines.append("| " + " | ".join(str(row[k]) for k in ("market", "rows", "missing_ohlc", "missing_volume", "nonpositive_prices", "invalid_ohlc", "negative_volume")) + " |")
    lines += ["", "Note: counts of integrity issues can overlap. This audit is read-only and does not alter database records."]
    return "\n".join(lines)


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured.")
    with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=20) as conn:
        report = fetch_report(conn)
    summary = summarize(report)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    markdown = render_markdown(summary)
    print(markdown)
    if SUMMARY_PATH:
        with open(SUMMARY_PATH, "a", encoding="utf-8") as f:
            f.write(markdown + "\n")


if __name__ == "__main__":
    main()
