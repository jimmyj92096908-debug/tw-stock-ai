"""Read-only data coverage and freshness audit for the Neon twstock database.

No schema changes, writes, market-data downloads, LINE messages, or credentials
are included in the report. Use a read-only Postgres role where available.
"""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

import psycopg
from psycopg.rows import dict_row


GLOBAL_DATES_SQL = """
SELECT
  (SELECT MAX(trade_date) FROM public.daily_prices WHERE close IS NOT NULL)
    AS latest_price_date,
  (SELECT MAX(trade_date) FROM public.daily_technicals)
    AS latest_technical_date,
  (SELECT MAX(trade_date) FROM public.daily_smc)
    AS latest_smc_date,
  (SELECT MAX(as_of_date) FROM public.daily_composite_scores
    WHERE total_score IS NOT NULL) AS latest_score_date
"""

COVERAGE_SQL = """
WITH per_stock AS (
  SELECT sm.market, sm.stock_id,
    MAX(p.trade_date) FILTER (WHERE p.close IS NOT NULL) AS last_price
  FROM public.stock_master sm
  LEFT JOIN public.daily_prices p
    ON p.market=sm.market AND p.stock_id=sm.stock_id
  GROUP BY sm.market, sm.stock_id
)
SELECT market, COUNT(*)::int AS universe,
  COUNT(*) FILTER (WHERE last_price IS NOT NULL)::int AS priced,
  COUNT(*) FILTER (WHERE last_price IS NULL)::int AS missing_prices,
  COUNT(*) FILTER (
    WHERE last_price IS NOT NULL
      AND last_price < %s::date - INTERVAL '7 days'
  )::int AS over_7_days_behind_latest
FROM per_stock
GROUP BY market ORDER BY market
"""

SCORE_MATCH_SQL = """
WITH newest AS (
  SELECT MAX(as_of_date) AS score_date
  FROM public.daily_composite_scores WHERE total_score IS NOT NULL
)
SELECT newest.score_date,
  COUNT(c.stock_id)::int AS scored,
  COUNT(c.stock_id) FILTER (WHERE p.close IS NOT NULL)::int AS matched_price,
  COUNT(c.stock_id) FILTER (WHERE p.close IS NULL)::int AS missing_price
FROM newest
LEFT JOIN public.daily_composite_scores c
  ON c.as_of_date=newest.score_date AND c.total_score IS NOT NULL
LEFT JOIN public.daily_prices p
  ON p.market=c.market AND p.stock_id=c.stock_id
 AND p.trade_date=c.as_of_date
GROUP BY newest.score_date
"""

SAMPLE_CODES = ("2330", "6488", "6213")
SAMPLES_SQL = """
SELECT sm.market,sm.stock_id,sm.stock_name,
  MAX(p.trade_date) FILTER (WHERE p.close IS NOT NULL) AS last_price
FROM public.stock_master sm
LEFT JOIN public.daily_prices p
  ON p.market=sm.market AND p.stock_id=sm.stock_id
WHERE sm.stock_id=ANY(%s)
GROUP BY sm.market,sm.stock_id,sm.stock_name
ORDER BY sm.market,sm.stock_id
"""


QUALITY_SQL = """
WITH p AS (
 SELECT COUNT(*)::int AS total_price_rows,
 COUNT(*) FILTER (WHERE close IS NOT NULL AND close<=0)::int AS invalid_close,
 COUNT(*) FILTER (WHERE volume<0)::int AS negative_volume,
 COUNT(*) FILTER (WHERE high IS NOT NULL AND low IS NOT NULL AND high<low)::int AS inverted_high_low,
 COUNT(*) FILTER (WHERE close IS NOT NULL AND high IS NOT NULL AND close>high)::int AS close_above_high,
 COUNT(*) FILTER (WHERE close IS NOT NULL AND low IS NOT NULL AND close<low)::int AS close_below_low,
 COUNT(*) FILTER (WHERE trade_date>CURRENT_DATE)::int AS future_price_date
 FROM public.daily_prices
), s AS (
 SELECT COUNT(*)::int AS total_score_rows,
 COUNT(*) FILTER (WHERE total_score IS NOT NULL AND (total_score<0 OR total_score>100))::int AS invalid_score,
 COUNT(*) FILTER (WHERE coverage_weight IS NOT NULL AND (coverage_weight<0 OR coverage_weight>1))::int AS invalid_score_coverage,
 COUNT(*) FILTER (WHERE as_of_date>CURRENT_DATE)::int AS future_score_date
 FROM public.daily_composite_scores
)
SELECT * FROM p CROSS JOIN s
"""


ANALYSIS_READINESS_SQL = """
SELECT
 (SELECT COUNT(*)::int FROM (SELECT market,stock_id FROM public.daily_prices
   WHERE close IS NOT NULL GROUP BY market,stock_id HAVING COUNT(*) >= 60) x) AS history_60d,
 (SELECT COUNT(*)::int FROM (SELECT market,stock_id FROM public.daily_prices
   WHERE close IS NOT NULL GROUP BY market,stock_id HAVING COUNT(*) >= 120) x) AS history_120d,
 (SELECT COUNT(*)::int FROM (SELECT market,stock_id FROM public.daily_prices
   WHERE close IS NOT NULL GROUP BY market,stock_id HAVING COUNT(*) >= 240) x) AS history_240d,
 (SELECT COUNT(DISTINCT (market,stock_id))::int FROM public.daily_technicals) AS technical_stocks,
 (SELECT COUNT(DISTINCT (market,stock_id))::int FROM public.daily_smc) AS smc_stocks,
 (SELECT COUNT(DISTINCT (market,stock_id))::int FROM public.daily_composite_scores
   WHERE total_score IS NOT NULL) AS scored_stocks,
 (SELECT COUNT(DISTINCT (market,stock_id))::int FROM public.daily_composite_scores
   WHERE total_score IS NOT NULL
     AND as_of_date = (SELECT MAX(trade_date) FROM public.daily_prices WHERE close IS NOT NULL)
 ) AS scored_latest_price_day
"""

INDICATOR_BACKLOG_SQL = """
WITH latest AS (
 SELECT MAX(trade_date) AS newest
 FROM public.daily_prices WHERE close IS NOT NULL
), qualified AS (
 SELECT market,stock_id,
        COUNT(*) FILTER(WHERE close IS NOT NULL)::int AS close_days,
        MAX(trade_date) FILTER(WHERE close IS NOT NULL) AS last_close
 FROM public.daily_prices
 WHERE stock_id <> '1808'
 GROUP BY market,stock_id
 HAVING COUNT(*) FILTER(WHERE close IS NOT NULL)>=60
), recent AS (
 SELECT q.market,q.stock_id,q.close_days,q.last_close
 FROM qualified q CROSS JOIN latest l
 WHERE q.last_close >= l.newest - INTERVAL '7 days'
), technicals AS (
 SELECT market,stock_id,COUNT(*)::int AS rows,
        MAX(trade_date) AS last_technical
 FROM public.daily_technicals GROUP BY market,stock_id
), smc AS (
 SELECT market,stock_id,COUNT(*)::int AS rows,
        MAX(trade_date) AS last_smc
 FROM public.daily_smc GROUP BY market,stock_id
), coverage AS (
 SELECT r.market,r.stock_id,r.close_days,r.last_close,
        COALESCE(t.rows,0) AS technical_rows,
        t.last_technical,
        COALESCE(s.rows,0) AS smc_rows,
        s.last_smc
 FROM recent r
 LEFT JOIN technicals t USING(market,stock_id)
 LEFT JOIN smc s USING(market,stock_id)
)
SELECT market,
 COUNT(*)::int AS eligible,
 COUNT(*) FILTER (WHERE technical_rows<close_days OR smc_rows<close_days
                  OR last_technical IS DISTINCT FROM last_close
                  OR last_smc IS DISTINCT FROM last_close)::int AS pending,
 COUNT(*) FILTER (WHERE technical_rows>=close_days AND smc_rows>=close_days
                  AND last_technical=last_close AND last_smc=last_close)::int AS complete,
 COUNT(*) FILTER (WHERE technical_rows=0 AND smc_rows=0)::int AS unstarted
FROM coverage
GROUP BY market ORDER BY market
"""

REFRESH_STATUS_SQL = """
SELECT CASE WHEN last_attempt_at IS NULL THEN 'never_attempted'
  ELSE last_status END AS status, COUNT(*)::int AS total
FROM public.market_data_refresh_state
GROUP BY 1 ORDER BY 1
"""


def iso_date(value: date | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def collect_audit(conn: Any) -> dict[str, Any]:
    """A snapshot of coverage without changing database state."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(GLOBAL_DATES_SQL)
        dates = cur.fetchone()
        latest = dates["latest_price_date"]
        # This one placeholder receives a trusted date read from the DB.
        cur.execute(COVERAGE_SQL, (latest,))
        coverage = [dict(row) for row in cur.fetchall()]
        cur.execute(SCORE_MATCH_SQL)
        score = dict(cur.fetchone())
        cur.execute(SAMPLES_SQL, (list(SAMPLE_CODES),))
        samples = [dict(row) for row in cur.fetchall()]
        # Early databases may not have this optional refresh-state table.
        cur.execute("SELECT to_regclass('public.market_data_refresh_state') AS name")
        exists = cur.fetchone()["name"] is not None
        refresh = []
        if exists:
            cur.execute(REFRESH_STATUS_SQL)
            refresh = [dict(row) for row in cur.fetchall()]
        cur.execute(QUALITY_SQL)
        quality = dict(cur.fetchone())
        cur.execute(ANALYSIS_READINESS_SQL)
        readiness = dict(cur.fetchone())
        # Exact same 60-session/freshness predicate as the bounded catch-up.
        # Aggregate counts only; no ticker lists, writes or personal data.
        cur.execute(INDICATOR_BACKLOG_SQL)
        backlog = [dict(row) for row in cur.fetchall()]

    return {
        "latest": {name: iso_date(value) for name, value in dict(dates).items()},
        "coverage": coverage,
        "score": {**score, "score_date": iso_date(score["score_date"])},
        "samples": [
            {**row, "last_price": iso_date(row["last_price"])}
            for row in samples
        ],
        "refresh_state": refresh,
        "quality": quality,
        "analysis_readiness": readiness,
        "indicator_backlog": backlog,
    }


def format_audit(audit: dict[str, Any]) -> str:
    latest = audit["latest"]
    lines = [
        "twstock 唯讀資料品質檢查",
        "行情：" + (latest["latest_price_date"] or "尚無"),
        "技術：" + (latest["latest_technical_date"] or "尚無"),
        "SMC：" + (latest["latest_smc_date"] or "尚無"),
        "評分：" + (latest["latest_score_date"] or "尚無"),
    ]
    total_universe = sum(row["universe"] for row in audit["coverage"])
    total_priced = sum(row["priced"] for row in audit["coverage"])
    lines.append(f"有行情股票：{total_priced}/{total_universe}")
    for row in audit["coverage"]:
        lines.append(
            f"{row['market']}：{row['priced']}/{row['universe']} 有行情；"
            f"無行情 {row['missing_prices']}；"
            f"落後最新行情超過 7 日 {row['over_7_days_behind_latest']}"
        )
    score = audit["score"]
    lines.append(
        f"評分日 {score['score_date'] or '尚無'}："
        f"評分 {score['scored']}；有同日收盤價 {score['matched_price']}；"
        f"缺同日價 {score['missing_price']}"
    )
    for row in audit["samples"]:
        lines.append(
            f"{row['stock_id']} {row['stock_name']}：{row['last_price'] or '無行情'}"
        )
    for row in audit["refresh_state"]:
        lines.append(f"輪替更新 {row['status']}：{row['total']}")
    quality = audit.get("quality")
    if quality is not None:
        price_issues = (
            "invalid_close", "negative_volume", "inverted_high_low",
            "close_above_high", "close_below_low", "future_price_date"
        )
        score_issues = (
            "invalid_score", "invalid_score_coverage", "future_score_date"
        )
        price_issue_count = sum(int(quality.get(name) or 0) for name in price_issues)
        score_issue_count = sum(int(quality.get(name) or 0) for name in score_issues)
        lines.append(
            f"價格資料品質：共 {int(quality['total_price_rows']):,} 筆；"
            f"異常條件命中 {price_issue_count} 次"
        )
        lines.append(
            f"評分資料品質：共 {int(quality['total_score_rows']):,} 筆；"
            f"異常條件命中 {score_issue_count} 次"
        )
        if price_issue_count or score_issue_count:
            lines.append("警告：發現行情或評分欄位異常，請先排查來源資料。")
    readiness = audit.get("analysis_readiness")
    if readiness is not None:
        lines.append(
            "歷史行情完整度：至少 60 日 {history_60d} 檔、"
            "120 日 {history_120d} 檔、240 日 {history_240d} 檔".format(**readiness)
        )
        lines.append(
            "技術指標 {technical_stocks} 檔／SMC {smc_stocks} 檔／"
            "有效評分 {scored_stocks} 檔；最新行情日有評分 "
            "{scored_latest_price_day} 檔".format(**readiness)
        )
        if readiness["scored_stocks"] < total_priced:
            lines.append("注意：有收盤行情不等於分析指標／評分已補齊。")
    backlog = audit.get("indicator_backlog", [])
    if backlog:
        pending_total = sum(int(r["pending"]) for r in backlog)
        eligible_total = sum(int(r["eligible"]) for r in backlog)
        for row in backlog:
            lines.append(
                f"指標候選 {row['market']}："
                f"符合 60 日且近期有行情 {row['eligible']} 檔；"
                f"待補 {row['pending']}；已補齊 {row['complete']}；"
                f"技術與 SMC 均未開始 {row['unstarted']}"
            )
        lines.append(f"技術／SMC 待補總量：{pending_total}/{eligible_total} 檔（不等於全市場）")
        if pending_total:
            lines.append("注意：補算程式通過測試不代表這些待補股票已實際寫入。")
    if latest["latest_price_date"] != latest["latest_score_date"]:
        lines.append("提醒：最新行情日與最新評分日不同，請勿混用。")
    if total_universe and total_priced < total_universe:
        lines.append("注意：資料尚未涵蓋全部候選股票，不可視為全市場分析。")
    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="唯讀檢查股票資料覆蓋率與日期")
    parser.add_argument("--json", action="store_true", help="JSON 形式輸出")
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL 未設定；請使用唯讀資料庫連線。")

    with psycopg.connect(url, connect_timeout=20, row_factory=dict_row) as conn:
        # All SQL statements are SELECT; read-only transaction blocks writes.
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            audit = collect_audit(conn)
    if args.json:
        print(json.dumps(audit, ensure_ascii=False, indent=2))
    else:
        print(format_audit(audit))


if __name__ == "__main__":
    main()
