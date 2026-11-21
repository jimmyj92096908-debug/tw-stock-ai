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


LATEST_VALID_DAY_COVERAGE_SQL = """
WITH latest_valid AS (
 SELECT market,stock_id,MAX(trade_date) AS last_close
 FROM public.daily_prices
 WHERE close IS NOT NULL AND close > 0
 GROUP BY market,stock_id
)
SELECT
 COUNT(*)::int AS priced_stocks,
 COUNT(*) FILTER (WHERE EXISTS (
   SELECT 1 FROM public.daily_technicals t
   WHERE t.market=l.market AND t.stock_id=l.stock_id
     AND t.trade_date=l.last_close
 ))::int AS technical_current,
 COUNT(*) FILTER (WHERE EXISTS (
   SELECT 1 FROM public.daily_smc s
   WHERE s.market=l.market AND s.stock_id=l.stock_id
     AND s.trade_date=l.last_close
 ))::int AS smc_current,
 COUNT(*) FILTER (WHERE EXISTS (
   SELECT 1 FROM public.daily_composite_scores c
   WHERE c.market=l.market AND c.stock_id=l.stock_id
     AND c.as_of_date=l.last_close AND c.total_score IS NOT NULL
 ))::int AS scored_current
FROM latest_valid l
"""



# Track the complete master denominator, eligible cohort and the EXACT
# same-stock/same-last-positive-close technical+SMC+composite intersection.
# One bounded aggregate query is appended to the existing scheduled READ ONLY
# monitor: NO additional workflow, no per-stock data artifact and no DB writes.
COHORT_INTERSECTION_SQL = """
WITH history AS (
 SELECT sm.market,sm.stock_id,
        COUNT(p.trade_date) FILTER(WHERE p.close>0)::int AS valid_days,
        MAX(p.trade_date) FILTER(WHERE p.close>0) AS last_valid
 FROM public.stock_master sm
 LEFT JOIN public.daily_prices p
   ON p.market=sm.market AND p.stock_id=sm.stock_id
 GROUP BY sm.market,sm.stock_id
), market_latest AS (
 SELECT MAX(trade_date) AS latest_valid
 FROM public.daily_prices WHERE close>0
), flags AS (
 SELECT h.market,h.stock_id,h.valid_days,h.last_valid,
        (h.stock_id<>'1808' AND h.valid_days>=60 AND
         h.last_valid>=l.latest_valid-INTERVAL '7 days') AS eligible,
        EXISTS(SELECT 1 FROM public.daily_technicals t
          WHERE t.market=h.market AND t.stock_id=h.stock_id
            AND t.trade_date=h.last_valid) AS has_tech,
        EXISTS(SELECT 1 FROM public.daily_smc s
          WHERE s.market=h.market AND s.stock_id=h.stock_id
            AND s.trade_date=h.last_valid) AS has_smc,
        EXISTS(SELECT 1 FROM public.daily_composite_scores c
          WHERE c.market=h.market AND c.stock_id=h.stock_id
            AND c.as_of_date=h.last_valid AND c.total_score IS NOT NULL)
          AS has_score
 FROM history h CROSS JOIN market_latest l
)
SELECT market,
 COUNT(*)::int AS master,
 COUNT(*) FILTER(WHERE valid_days=0)::int AS no_valid_price,
 COUNT(*) FILTER(WHERE valid_days>0 AND valid_days<60
                 AND stock_id<>'1808')::int AS short_history,
 COUNT(*) FILTER(WHERE stock_id='1808' AND valid_days>0)::int
   AS research_excluded,
 COUNT(*) FILTER(WHERE valid_days>=60 AND stock_id<>'1808'
                 AND NOT eligible)::int AS stale_sufficient_history,
 COUNT(*) FILTER(WHERE eligible)::int AS eligible,
 COUNT(*) FILTER(WHERE eligible AND has_tech)::int AS tech_current,
 COUNT(*) FILTER(WHERE eligible AND has_smc)::int AS smc_current,
 COUNT(*) FILTER(WHERE eligible AND has_tech AND has_smc)::int
   AS indicator_current,
 COUNT(*) FILTER(WHERE eligible AND has_score)::int AS score_current,
 COUNT(*) FILTER(WHERE eligible AND has_tech AND has_smc AND has_score)::int
   AS matched_current
FROM flags
GROUP BY market ORDER BY market
"""


def validate_cohort_intersection(markets: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify denominator partition + same-day score intersection, fail closed."""
    fields=("master","no_valid_price","short_history",
            "research_excluded","stale_sufficient_history","eligible",
            "tech_current","smc_current","indicator_current","score_current",
            "matched_current")
    if not isinstance(markets,list) or not 1<=len(markets)<=2:
        raise ValueError("TWSE/TPEx aggregate snapshots required")
    seen=set()
    totals={name:0 for name in fields}
    for record in markets:
        if not isinstance(record,dict) or record.get("market") not in ("twse","tpex"):
            raise ValueError("Unexpected market cohort")
        if record["market"] in seen:
            raise ValueError("Duplicated market coverage row")
        seen.add(record["market"])
        for field in fields:
            value=record.get(field)
            if type(value) is not int or value<0:
                raise ValueError("Missing or invalid coverage aggregate: "+field)
            totals[field]+=value
        if sum(record[k] for k in (
            "no_valid_price","short_history","research_excluded",
            "stale_sufficient_history","eligible"))!=record["master"]:
            raise ValueError("Coverage master denominator does not partition")
        if (max(record["tech_current"],record["smc_current"],
                record["score_current"])>record["eligible"] or
            record["indicator_current"]>min(record["tech_current"],record["smc_current"]) or
            record["matched_current"]>min(record["indicator_current"],record["score_current"])):
            raise ValueError("Same-stock/same-date intersection mathematically inconsistent")
    if totals["master"]<1:
        raise ValueError("Missing valid stock-master denominator")
    return {
        "master":totals["master"],
        "eligible":totals["eligible"],
        "complete":totals["matched_current"],
        "coverage_fraction_eligible":(
            round(totals["matched_current"]/totals["eligible"],6)
            if totals["eligible"] else None),
        "coverage_fraction_master":round(totals["matched_current"]/totals["master"],6),
        "blocking_cohorts":{
            key:totals[key] for key in ("no_valid_price","short_history",
                "research_excluded","stale_sufficient_history")},
        "missing_eligible_current_indicators":totals["eligible"]-totals["indicator_current"],
        "missing_eligible_current_composite":totals["eligible"]-totals["score_current"],
        "missing_eligible_matched_full_stack":totals["eligible"]-totals["matched_current"],
        "all_eligible_current_complete":(
            totals["eligible"]>0 and totals["matched_current"]==totals["eligible"]),
        "all_master_current_complete":(
            totals["matched_current"]==totals["master"]),
        "not_evidence_of_investment_alpha":True,
        "production_writes":False,
        "line_signals_enabled":False,
        "orders_enabled":False,
    }

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
        EXISTS(SELECT 1 FROM public.daily_technicals tday
          WHERE tday.market=r.market AND tday.stock_id=r.stock_id
            AND tday.trade_date=r.last_close) AS has_latest_technical,
        COALESCE(s.rows,0) AS smc_rows,
        EXISTS(SELECT 1 FROM public.daily_smc sday
          WHERE sday.market=r.market AND sday.stock_id=r.stock_id
            AND sday.trade_date=r.last_close) AS has_latest_smc
 FROM recent r
 LEFT JOIN technicals t USING(market,stock_id)
 LEFT JOIN smc s USING(market,stock_id)
)
SELECT market,
 COUNT(*)::int AS eligible,
 COUNT(*) FILTER (WHERE technical_rows<close_days OR smc_rows<close_days
                  OR NOT has_latest_technical OR NOT has_latest_smc)::int AS pending,
 COUNT(*) FILTER (WHERE technical_rows>=close_days AND smc_rows>=close_days
                  AND has_latest_technical AND has_latest_smc)::int AS complete,
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
        cur.execute(LATEST_VALID_DAY_COVERAGE_SQL)
        latest_valid_coverage = dict(cur.fetchone())
        cur.execute(COHORT_INTERSECTION_SQL)
        same_day_cohorts = [dict(row) for row in cur.fetchall()]
        matching_coverage = validate_cohort_intersection(same_day_cohorts)

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
        "latest_valid_day_coverage": latest_valid_coverage,
        "cohort_by_market": same_day_cohorts,
        "matched_cohort_coverage": matching_coverage,
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
    current = audit.get("latest_valid_day_coverage")
    if current is not None:
        lines.append(
            "各股最新有效收盤日覆蓋：價格 {priced_stocks} 檔；技術 {technical_current} 檔；"
            "SMC {smc_current} 檔；有效綜合評分 {scored_current} 檔".format(**current)
        )
        if current["scored_current"] < current["priced_stocks"]:
            lines.append("注意：歷史曾有評分不代表各股最新有效收盤日有有效評分。")
    matched = audit.get("matched_cohort_coverage")
    if matched is not None:
        fraction=matched["coverage_fraction_eligible"]
        lines.append(
            "同股同最新有效日完整指標＋SMC＋評分："
            f"{matched['complete']}/{matched['eligible']} 檔，"
            f"目前合格池 {fraction:.1%}" if fraction is not None else
            "同股同最新有效日完整指標＋SMC＋評分：目前沒有合格股票"
        )
        lines.append(
            f"全市場清單分母 {matched['master']} 檔；"
            f"完整研究覆蓋率 {matched['coverage_fraction_master']:.1%}；"
            f"少於 60 日有效行情 {matched['blocking_cohorts']['short_history']} 檔；"
            f"無有效收盤 {matched['blocking_cohorts']['no_valid_price']} 檔"
        )
        if not matched["all_eligible_current_complete"]:
            lines.append(
                f"警告：合格池尚有 {matched['missing_eligible_matched_full_stack']} "
                "檔沒有同日完整研究評分；不可宣稱 100%"
            )
        lines.append("研究資料達標不代表 AI 模型績效合格或可實際下單。")
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
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            conn.execute("SET LOCAL statement_timeout = '30000ms'")
            audit = collect_audit(conn)
    if args.json:
        print(json.dumps(audit, ensure_ascii=False, indent=2))
    else:
        print(format_audit(audit))


if __name__ == "__main__":
    main()
