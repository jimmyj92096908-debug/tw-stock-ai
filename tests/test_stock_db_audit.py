"""Offline tests for the read-only stock data coverage audit."""
import unittest
from datetime import date
from pathlib import Path

from src.stock_db_audit import (
    COVERAGE_SQL, GLOBAL_DATES_SQL, SCORE_MATCH_SQL, SAMPLES_SQL,
    REFRESH_STATUS_SQL, QUALITY_SQL, ANALYSIS_READINESS_SQL, INDICATOR_BACKLOG_SQL, LATEST_VALID_DAY_COVERAGE_SQL,
    COHORT_INTERSECTION_SQL, validate_cohort_intersection, collect_audit, format_audit, iso_date,
)


class _Cursor:
    def __init__(self, refresh_exists=True):
        self.refresh_exists = refresh_exists
        self.calls = []
        self.sql = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.sql = sql
        self.calls.append((sql, params))
        # This test intentionally fails on accidental INSERT/UPDATE/DELETE.
        assert sql.lstrip().upper().startswith("SELECT") or (
            sql.lstrip().upper().startswith("WITH")
        )

    def fetchone(self):
        if self.sql == GLOBAL_DATES_SQL:
            return {
                "latest_price_date": date(2026, 11, 19),
                "latest_technical_date": date(2026, 11, 19),
                "latest_smc_date": date(2026, 11, 19),
                "latest_score_date": date(2026, 11, 18),
            }
        if self.sql == SCORE_MATCH_SQL:
            return {
                "score_date": date(2026, 11, 18),
                "scored": 18, "matched_price": 17, "missing_price": 1,
            }
        if self.sql == ANALYSIS_READINESS_SQL:
            return {
                "history_60d": 30, "history_120d": 20,
                "history_240d": 18, "technical_stocks": 18,
                "smc_stocks": 18, "scored_stocks": 15,
                "scored_latest_price_day": 12,
            }
        if self.sql == LATEST_VALID_DAY_COVERAGE_SQL:
            return {"priced_stocks": 40, "technical_current": 12,
                    "smc_current": 11, "scored_current": 10}
        if self.sql == QUALITY_SQL:
            return {
                "total_price_rows": 49392, "invalid_close": 0,
                "negative_volume": 0, "inverted_high_low": 0,
                "close_above_high": 0, "close_below_low": 0,
                "future_price_date": 0, "total_score_rows": 37118,
                "invalid_score": 0, "invalid_score_coverage": 0,
                "future_score_date": 0,
            }
        if "to_regclass" in self.sql:
            return {"name": "market_data_refresh_state" if self.refresh_exists else None}
        raise AssertionError("Unexpected fetchone")

    def fetchall(self):
        if self.sql == COVERAGE_SQL:
            return [
                {"market": "twse", "universe": 1093, "priced": 21,
                 "missing_prices": 1072, "over_7_days_behind_latest": 5},
                {"market": "tpex", "universe": 898, "priced": 19,
                 "missing_prices": 879, "over_7_days_behind_latest": 5},
            ]
        if self.sql == SAMPLES_SQL:
            return [
                {"market": "twse", "stock_id": "2330",
                 "stock_name": "台積電", "last_price": date(2026, 10, 30)},
                {"market": "tpex", "stock_id": "6488",
                 "stock_name": "環球晶", "last_price": None},
            ]
        if self.sql == COHORT_INTERSECTION_SQL:
            return [
                {"market":"tpex","master":898,"no_valid_price":8,
                 "short_history":867,"research_excluded":0,
                 "stale_sufficient_history":1,"eligible":22,
                 "tech_current":21,"smc_current":21,"indicator_current":21,
                 "score_current":20,"matched_current":20},
                {"market":"twse","master":1093,"no_valid_price":1,
                 "short_history":4,"research_excluded":1,
                 "stale_sufficient_history":0,"eligible":1087,
                 "tech_current":1087,"smc_current":1087,"indicator_current":1087,
                 "score_current":1087,"matched_current":1087},
            ]
        if self.sql == INDICATOR_BACKLOG_SQL:
            return [
                {"market":"tpex","eligible":21,"pending":0,"complete":21,"unstarted":0},
                {"market":"twse","eligible":1085,"pending":1044,"complete":41,"unstarted":942},
            ]
        if self.sql == REFRESH_STATUS_SQL:
            return [
                {"status": "success", "total": 14},
                {"status": "never_attempted", "total": 1977},
            ]
        raise AssertionError("Unexpected fetchall")


class _Connection:
    def __init__(self, refresh_exists=True):
        self.cur = _Cursor(refresh_exists=refresh_exists)

    def cursor(self, **_kwargs):
        return self.cur


class StockAuditTests(unittest.TestCase):
    def test_collect_and_format_readonly_snapshot(self):
        conn = _Connection()
        result = collect_audit(conn)
        self.assertEqual(result["latest"]["latest_price_date"], "2026-11-19")
        self.assertEqual(result["latest"]["latest_score_date"], "2026-11-18")
        self.assertEqual(result["score"]["matched_price"], 17)
        self.assertEqual(result["samples"][0]["last_price"], "2026-10-30")
        self.assertEqual(len(conn.cur.calls), 11)
        self.assertEqual(conn.cur.calls[1][1], (date(2026, 11, 19),))
        self.assertEqual(conn.cur.calls[3][1], (["2330", "6488", "6213"],))

        output = format_audit(result)
        self.assertIn("有行情股票：40/1991", output)
        self.assertIn("評分日 2026-11-18：評分 18；有同日收盤價 17", output)
        self.assertIn("輪替更新 never_attempted：1977", output)
        self.assertIn("不可視為全市場分析", output)
        self.assertIn("價格資料品質：共 49,392 筆；異常條件命中 0 次", output)
        self.assertIn("評分資料品質：共 37,118 筆；異常條件命中 0 次", output)
        self.assertIn("最新行情日與最新評分日不同", output)
        self.assertIn("至少 60 日 30 檔、120 日 20 檔、240 日 18 檔", output)
        self.assertIn("技術指標 18 檔／SMC 18 檔／有效評分 15 檔", output)
        self.assertIn("有收盤行情不等於分析指標", output)
        self.assertIn("待補 1044", output)
        self.assertIn("技術／SMC 待補總量：1044/1106", output)
        self.assertEqual(result["indicator_backlog"][1]["unstarted"], 942)
        self.assertEqual(conn.cur.calls[-3][0], INDICATOR_BACKLOG_SQL)
        self.assertEqual(conn.cur.calls[-2][0], LATEST_VALID_DAY_COVERAGE_SQL)
        self.assertEqual(conn.cur.calls[-1][0], COHORT_INTERSECTION_SQL)
        self.assertEqual(result["matched_cohort_coverage"]["complete"],1107)
        self.assertEqual(result["matched_cohort_coverage"]["eligible"],1109)
        self.assertEqual(result["matched_cohort_coverage"]["blocking_cohorts"]["no_valid_price"],9)
        self.assertFalse(result["matched_cohort_coverage"]["all_eligible_current_complete"])
        self.assertIn("同股同最新有效日完整指標＋SMC＋評分：1107/1109 檔", output)
        self.assertIn("研究資料達標不代表 AI 模型績效合格", output)
        self.assertEqual(result["latest_valid_day_coverage"]["scored_current"], 10)
        self.assertIn("各股最新有效收盤日覆蓋：價格 40 檔；技術 12 檔", output)

    def test_exact_intersection_coverage_partition_refuses_false_success(self):
        good=[
            {"market":"twse","master":11,"no_valid_price":1,
             "short_history":2,"research_excluded":1,"stale_sufficient_history":1,
             "eligible":6,"tech_current":6,"smc_current":6,
             "indicator_current":6,"score_current":6,"matched_current":6}
        ]
        out=validate_cohort_intersection(good)
        self.assertTrue(out["all_eligible_current_complete"])
        self.assertFalse(out["all_master_current_complete"])
        self.assertEqual(out["coverage_fraction_eligible"],1)
        self.assertEqual(out["coverage_fraction_master"],round(6/11,6))
        self.assertEqual(out["blocking_cohorts"]["short_history"],2)
        self.assertFalse(out["not_evidence_of_investment_alpha"] is False)
        self.assertFalse(out["production_writes"])
        self.assertFalse(out["orders_enabled"])
        for field,value in (
            ("master",10), ("eligible",7),("matched_current",7),
            ("score_current",5),("indicator_current",5),
            ("tech_current",4),("short_history",True),
            ("research_excluded",-1)
        ):
            with self.subTest(field=field,value=value):
                with self.assertRaises(ValueError):
                    validate_cohort_intersection([{**good[0],field:value}])
        with self.assertRaisesRegex(ValueError,"Duplicated"):
            validate_cohort_intersection(good+good)
        with self.assertRaisesRegex(ValueError,"market"):
            validate_cohort_intersection([{**good[0],"market":"other"}])
        self.assertIn("COUNT(*) FILTER(WHERE eligible AND has_tech AND has_smc AND has_score)",
                      COHORT_INTERSECTION_SQL)
        self.assertIn("c.as_of_date=h.last_valid AND c.total_score IS NOT NULL",
                      COHORT_INTERSECTION_SQL)
        self.assertIn("p.close>0",COHORT_INTERSECTION_SQL)
        for command in ("INSERT ","UPDATE ","DELETE ","DROP "):
            self.assertNotIn(command,COHORT_INTERSECTION_SQL)

    def test_exact_daily_monitor_is_existing_job_without_extra_paid_scheduler(self):
        root=Path(__file__).resolve().parents[1]
        wf=(root/".github/workflows/twstock-data-quality-monitor.yml").read_text(encoding="utf-8")
        self.assertIn("cohort=audit[\"matched_cohort_coverage\"]",wf)
        self.assertIn("cohort['complete']",wf)
        self.assertIn("cohort['eligible']",wf)
        self.assertIn("cohort['coverage_fraction_master']",wf)
        self.assertIn("No candidate stocks",wf)
        self.assertIn("twstock-readonly-quality-monitor",wf)
        self.assertIn("0 20 * * 1-5",wf)
        self.assertEqual(wf.count("    - cron:"),1)
        self.assertNotIn("curl ",wf)
        self.assertNotIn("LINE_CHANNEL",wf)
        source=(root/"src/stock_db_audit.py").read_text(encoding="utf-8")
        self.assertIn("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",source)
        self.assertIn("SET LOCAL statement_timeout = '30000ms'",source)

    def test_empty_eligible_cohort_cannot_pass_100pct(self):
        only_missing=[
            {"market":"tpex","master":4,"no_valid_price":2,"short_history":2,
             "research_excluded":0,"stale_sufficient_history":0,"eligible":0,
             "tech_current":0,"smc_current":0,"indicator_current":0,
             "score_current":0,"matched_current":0}
        ]
        out=validate_cohort_intersection(only_missing)
        self.assertIsNone(out["coverage_fraction_eligible"])
        self.assertEqual(out["coverage_fraction_master"],0)
        self.assertFalse(out["all_eligible_current_complete"])
        self.assertFalse(out["all_master_current_complete"])

    def test_latest_valid_close_coverage_requires_exact_day_and_non_null_score(self):
        self.assertIn("close > 0", LATEST_VALID_DAY_COVERAGE_SQL)
        self.assertIn("t.trade_date=l.last_close", LATEST_VALID_DAY_COVERAGE_SQL)
        self.assertIn("s.trade_date=l.last_close", LATEST_VALID_DAY_COVERAGE_SQL)
        self.assertIn("c.as_of_date=l.last_close AND c.total_score IS NOT NULL", LATEST_VALID_DAY_COVERAGE_SQL)
        self.assertIn("各股最新有效收盤日覆蓋", format_audit(collect_audit(_Connection())))

    def test_optional_refresh_table_can_be_absent(self):
        conn = _Connection(refresh_exists=False)
        snapshot = collect_audit(conn)
        self.assertEqual(snapshot["refresh_state"], [])
        self.assertEqual(len(conn.cur.calls), 10)

    def test_quality_warnings_report_flagged_rows(self):
        snapshot = collect_audit(_Connection())
        snapshot["quality"]["negative_volume"] = 1
        snapshot["quality"]["invalid_score"] = 2
        output = format_audit(snapshot)
        self.assertIn("價格資料品質：共 49,392 筆；異常條件命中 1 次", output)
        self.assertIn("評分資料品質：共 37,118 筆；異常條件命中 2 次", output)
        self.assertIn("發現行情或評分欄位異常", output)
        self.assertIn("FROM public.daily_prices", QUALITY_SQL)
        self.assertIn("FROM public.daily_composite_scores", QUALITY_SQL)

    def test_indicator_backlog_query_matches_catchup_eligibility_and_is_readonly(self):
        from src.batch_indicator_catchup import CANDIDATES_SQL
        for condition in ("FILTER(WHERE close IS NOT NULL)", "stock_id <> '1808'",
                          "INTERVAL '7 days'", "COUNT(*) FILTER (WHERE technical_rows<close_days"):
            self.assertIn(condition, INDICATOR_BACKLOG_SQL)
        self.assertIn(">=60", INDICATOR_BACKLOG_SQL)
        self.assertIn("latest_close", CANDIDATES_SQL)
        # Match selection/proof by actual latest date, not only legacy totals.
        for condition in (
            "NOT has_latest_technical",
            "NOT has_latest_smc",
            "has_latest_technical AND has_latest_smc",
        ):
            self.assertIn(condition, INDICATOR_BACKLOG_SQL)
        self.assertIn("NOT has_latest_technical",CANDIDATES_SQL)
        self.assertIn("NOT has_latest_smc",CANDIDATES_SQL)
        self.assertIn("tday.trade_date=r.last_close",INDICATOR_BACKLOG_SQL)
        self.assertIn("sday.trade_date=r.last_close",INDICATOR_BACKLOG_SQL)
        for command in ("INSERT ", "UPDATE ", "DELETE ", "DROP "):
            self.assertNotIn(command, INDICATOR_BACKLOG_SQL)

    def test_null_date_and_empty_composite_count_not_fabricated(self):
        self.assertIsNone(iso_date(None))
        self.assertEqual(iso_date(date(2026, 11, 19)), "2026-11-19")
        self.assertIn("COUNT(c.stock_id)::int AS scored", SCORE_MATCH_SQL)
        self.assertNotIn("COUNT(*)::int AS scored", SCORE_MATCH_SQL)


if __name__ == "__main__":
    unittest.main()
