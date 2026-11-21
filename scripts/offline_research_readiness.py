"""Assemble an offline, non-promotional research readiness JSON + Markdown note.

Inputs are local verified audit/evaluation files; this CLI contains no DB, LINE,
broker or HTTP code. Coverage attainment and investment alpha are separate.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.research_coverage_acceptance import acceptance
from src.research_execution_costs import stress_test
from src.research_fundamental_pit import asof_fundamentals
from src.research_anomaly_monitor import score_drift


def _as_file(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def assemble_report(*,before,after,evaluation=None,cost_inputs=None,
                    fundamentals=None,as_of_close=None,score_snapshots=None):
    coverage=acceptance(before,after)
    eval_data=evaluation or {}
    if eval_data and not isinstance(eval_data,dict):
        raise ValueError("Saved evaluation must be a JSON object")
    holdout=eval_data.get("holdout",{}) if isinstance(eval_data.get("holdout",{}),dict) else {}
    holdout_excess=holdout.get("model_mean_net_excess")
    if isinstance(holdout_excess,bool) or not isinstance(holdout_excess,(int,float)):
        holdout_excess=None
    else:
        from math import isfinite
        if not isfinite(holdout_excess):
            holdout_excess=None
    if fundamentals is not None and not as_of_close:
        raise ValueError("Explicit market-close cutoff required for fundamentals")
    if score_snapshots is not None and (not isinstance(score_snapshots,list) or len(score_snapshots)!=2):
        raise ValueError("Exactly two prior/after score snapshots required")
    result={
        "schema_version":1,
        "coverage_acceptance":coverage,
        "historical_model_evidence":{
            "saved_holdout_excess_decimal":holdout_excess,
            "prior_holdout_not_pristine":True,
            "independent_future_model_proof":False,
            "historical_gate_passed":False,
        },
        "cost_stress":stress_test(**cost_inputs) if cost_inputs is not None else None,
        "fundamental_asof":asof_fundamentals(fundamentals,as_of_close=as_of_close) if fundamentals is not None else None,
        "score_shift":score_drift(*score_snapshots) if score_snapshots is not None else None,
        "fundamental_live_model_trained":False,
        "data_mode":"OFFLINE_LOCAL_JSON_ONLY",
        "permissions_scope":"offline_research_and_test_only",
        "payment_or_quota_upgrade_authorized":False,
        "database_modified":False,
        "line_webhook_changed":False,
        "line_messages_sent":False,
        "orders_enabled":False,
        "trade_recommendations_approved":False,
    }
    return result


def render_markdown(data):
    cov=data["coverage_acceptance"]
    evidence=data["historical_model_evidence"]
    holdout=evidence["saved_holdout_excess_decimal"]
    holdout_str=(f"{holdout*100:+.2f}%" if holdout is not None
                 else "無已驗證的模型樣本外數值")
    lines=[
        "# 台股 AI 研究驗收（僅離線研究）",
        "",
        f"- 最新價格日：{cov['latest_price_date']}",
        f"- 技術＋SMC：{cov['technical_and_smc_current']}/{cov['universe']}",
        f"- 有效評分：{cov['scored_current']}/{cov['universe']}",
        f"- 同一股票同一天完成三項的數量：{cov['verified_scored_and_both_current'] if cov['verified_scored_and_both_current'] is not None else '尚未取得獨立交集證據'}",
        f"- 50% 覆蓋率驗收狀態：{cov['status']}",
        f"- 既有樣本外淨超額研究數值：{holdout_str}",
        "- 研究資料達標並不代表投資模型已證明有效。",
        "- 舊 holdout 曾被檢視，不能冒稱為全新獨立驗證。",
    ]
    if data["cost_stress"] is not None:
        lines.append("- 成本壓測：已產生假設情境；非真實成交或流動性保證。")
    if data["fundamental_asof"] is not None:
        lines.append("- 基本面：僅使用訊號截止前公布且已登錄的資料。")
    if data["score_shift"] is not None:
        lines.append(f"- 分數漂移：{data['score_shift']['status']}")
    lines.extend(["- 未寫入正式資料庫、未發送 LINE、未啟動交易或付費升級。",""])
    return "\n".join(lines)


def main():
    p=argparse.ArgumentParser(description="Offline-only investment research evidence pack")
    p.add_argument("--before",type=Path,required=True)
    p.add_argument("--after",type=Path,required=True)
    p.add_argument("--evaluation",type=Path)
    p.add_argument("--cost-inputs",type=Path)
    p.add_argument("--fundamentals",type=Path)
    p.add_argument("--as-of-close")
    p.add_argument("--score-before",type=Path)
    p.add_argument("--score-after",type=Path)
    p.add_argument("--output-json",type=Path,required=True)
    p.add_argument("--output-md",type=Path,required=True)
    args=p.parse_args()
    if (args.score_before is None)!=(args.score_after is None):
        p.error("Both before/after score snapshots are required")
    snap=([_as_file(args.score_before),_as_file(args.score_after)]
          if args.score_before is not None else None)
    report=assemble_report(before=_as_file(args.before),
                           after=_as_file(args.after),
                           evaluation=_as_file(args.evaluation) if args.evaluation else None,
                           cost_inputs=_as_file(args.cost_inputs) if args.cost_inputs else None,
                           fundamentals=_as_file(args.fundamentals) if args.fundamentals else None,
                           as_of_close=args.as_of_close,
                           score_snapshots=snap)
    args.output_json.parent.mkdir(parents=True,exist_ok=True)
    args.output_md.parent.mkdir(parents=True,exist_ok=True)
    args.output_json.write_text(json.dumps(report,ensure_ascii=False,indent=2,
                                           allow_nan=False)+"\n",encoding="utf-8")
    args.output_md.write_text(render_markdown(report),encoding="utf-8")
    print(json.dumps({"status":report["coverage_acceptance"]["status"],
                      "report_json":str(args.output_json),
                      "report_markdown":str(args.output_md),
                      "orders_enabled":False},ensure_ascii=False))


if __name__=="__main__":
    main()
