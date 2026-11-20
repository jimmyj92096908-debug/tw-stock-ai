"""Machine-verifiable phase-one RESEARCH MVP acceptance (no database access).

Consumes the actual, already-published research-report.json from the Neon
READ ONLY research workflow. This acceptance is deliberately *not* approval
of LINE cutover, unattended cron reliability, a fully covered stock universe,
alpha, trade signals, or broker orders.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path


def _count(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f"Invalid acceptance count: {name}")
    return value


def accept(report):
    if report.get("schema_version") != 1:
        raise ValueError("Unsupported research report schema")
    if report.get("abstain") is not True:
        raise ValueError("Research model must explicitly abstain")
    for name in ("live_trading_approved", "line_stock_gateway_enabled",
                 "holdout_research_gate_passed"):
        if report.get(name) is not False:
            raise ValueError(f"Unsafe release gate: {name}")
    if report.get("research_report_available") is not True:
        raise ValueError("Research report is not available")
    market_day = report.get("market_date")
    score_day = report.get("score_date")
    try:
        valid_date = date.fromisoformat(market_day)
    except (TypeError, ValueError):
        raise ValueError("Missing or malformed verified market date") from None
    if market_day != score_day:
        raise ValueError("Price and score dates must match for acceptance")
    try:
        generated = report["generated_at_utc"]
        if not isinstance(generated, str) or not generated:
            raise ValueError("Missing report generation timestamp")
    except KeyError:
        raise ValueError("Missing report generation timestamp") from None
    if not report.get("model_version"):
        raise ValueError("Missing frozen research model version")

    counts = {
        k: _count(report.get(k), k) for k in (
            "candidate_stocks", "stocks_with_prices", "technical_stocks",
            "smc_stocks", "scored_stocks", "research_eligible_universe",
            "indicator_eligible", "indicator_pending", "indicator_complete",
            "indicator_unstarted", "quality_violations", "holdout_dates"
        )
    }
    if not (counts["candidate_stocks"] > 0 and
            0 < counts["stocks_with_prices"] <= counts["candidate_stocks"] and
            0 < counts["indicator_complete"] <= counts["indicator_eligible"] and
            counts["indicator_pending"] + counts["indicator_complete"] == counts["indicator_eligible"] and
            counts["indicator_unstarted"] <= counts["indicator_pending"]):
        raise ValueError("Inconsistent live stock and indicator coverage")
    if (min(counts["technical_stocks"],counts["smc_stocks"],counts["scored_stocks"]) == 0
            or counts["indicator_complete"] > counts["technical_stocks"]
            or counts["indicator_complete"] > counts["smc_stocks"]
            or not 0 < counts["research_eligible_universe"] <= counts["scored_stocks"]):
        raise ValueError("Missing usable technical, SMC, scores or research universe")
    if counts["quality_violations"] != 0:
        raise ValueError("Live data quality violations block sign-off")
    if counts["holdout_dates"] == 0:
        raise ValueError("Missing documented research holdout evaluation")
    if (not isinstance(report.get("research_ranked"),list) or
            not report["research_ranked"] or
            len(report["research_ranked"])>counts["research_eligible_universe"]):
        raise ValueError("Missing bounded, nonempty research ranking")
    markets = report.get("indicator_backlog_by_market")
    if (not isinstance(markets,list) or
            sorted(str(x.get("market")) for x in markets) != ["tpex","twse"]):
        raise ValueError("Missing exact TWSE and TPEx indicator coverage")
    for field in ("eligible","pending","complete","unstarted"):
        if sum(_count(item.get(field),field) for item in markets) != counts["indicator_"+field]:
            raise ValueError("Research report market coverage does not reconcile")
    try:
        excess = float(report["holdout_mean_net_excess"])
    except (TypeError,ValueError,KeyError):
        raise ValueError("Missing model holdout evidence") from None
    if not -10 < excess < 10:
        raise ValueError("Invalid model holdout performance")

    # This is an acceptance certificate for the original research-only
    # phase. Unseen future cron events and LINE E2E cannot be certified from
    # one point-in-time read-only research artifact.
    return {
        "schema_version": 1,
        "phase": "phase_one_read_only_research_mvp",
        "result": "accepted",
        "core_research_mvp_accepted": True,
        "market_date": valid_date.isoformat(),
        "score_date": score_day,
        "report_generated_at_utc": generated,
        "frozen_research_model": report["model_version"],
        "stocks_with_prices": counts["stocks_with_prices"],
        "candidate_stocks": counts["candidate_stocks"],
        "research_eligible_universe": counts["research_eligible_universe"],
        "scored_stocks": counts["scored_stocks"],
        "indicator_complete": counts["indicator_complete"],
        "indicator_pending": counts["indicator_pending"],
        "quality_violations": counts["quality_violations"],
        "model_holdout_mean_net_excess": excess,
        "holdout_research_gate_passed": False,
        "live_trading_approved": False,
        "line_webhook_cutover_verified": False,
        "research_only": True,
        "other_scope": {
            "whole_market_indicator_backfill": "ongoing_not_a_phase_one_research_mvp_gate",
            "unattended_cron_run": "requires_independent_github_schedule_run_evidence",
            "line_candidate_cutover": "blocked_until_credentials_signed_canary_and_real_e2e",
            "trading_or_line_signals": "disabled_due_to_unapproved_model_performance",
        },
    }


def markdown(value):
    return "\n".join([
        "# 第一階段核心研究 MVP：驗收通過",
        "",
        f"正式 Neon 行情日／評分日：{value['market_date']}。"
        f"研究報告生成時間（UTC）：{value['report_generated_at_utc']}。",
        "",
        f"- 真實有價股票：{value['stocks_with_prices']:,}/{value['candidate_stocks']:,} 檔",
        f"- 技術／SMC 已補齊：{value['indicator_complete']:,} 檔；待補算：{value['indicator_pending']:,} 檔",
        f"- 有效綜合評分：{value['scored_stocks']:,} 檔；研究排名合格：{value['research_eligible_universe']:,} 檔",
        f"- 價格與評分資料品質異常：{value['quality_violations']} 項",
        f"- 研究模型：{value['frozen_research_model']}；樣本外平均淨超額 {value['model_holdout_mean_net_excess']*100:+.2f}%",
        "",
        "**此驗收只核准唯讀研究 MVP，不核准獲利宣稱、買賣訊號或真實下單。**",
        "尚待另外驗證：首次無人值守排程的真實 schedule 事件、完整股票覆蓋、LINE 頻道憑證與簽章／真實訊息 E2E。",
        "",
    ])+"\n"


def main():
    parser=argparse.ArgumentParser(description="Research-only phase-one MVP evidence acceptance")
    parser.add_argument("--report",type=Path,required=True)
    parser.add_argument("--outdir",type=Path,required=True)
    args=parser.parse_args()
    report=json.loads(args.report.read_text(encoding="utf-8"))
    accepted=accept(report)
    args.outdir.mkdir(parents=True,exist_ok=True)
    (args.outdir/"first-stage-acceptance.json").write_text(
        json.dumps(accepted,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    status=markdown(accepted)
    (args.outdir/"first-stage-acceptance.md").write_text(status,encoding="utf-8")
    print(status)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as stream:
            stream.write(status)


if __name__=="__main__":
    main()
