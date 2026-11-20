"""Render an offline-viewable daily research dashboard from verified read-only JSON.

This formatter never connects to databases, LINE, or a brokerage.
All numeric metrics come from the existing database-audit/ranking reports.
The UI ALWAYS declares trading and delivery disabled.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path

QUALITY_FIELDS = (
    "invalid_close", "negative_volume", "inverted_high_low",
    "close_above_high", "close_below_low", "future_price_date",
    "invalid_score", "invalid_score_coverage", "future_score_date",
)


def _int(value):
    result = int(value)
    if result < 0:
        raise ValueError("Negative statistics are invalid")
    return result


def _safe_cell(value):
    return str(value).replace("|", r"\|").replace("\r", " ").replace("\n", " ")


def build_summary(audit, ranking, evaluation, *, generated_at=None):
    """Fail closed on inconsistent evidence; never imply investment approval."""
    if ranking.get("abstain") is not True or ranking.get("live_trading_approved") is not False:
        raise ValueError("Research ranking must explicitly abstain")
    if evaluation.get("live_trading_approved") is not False or evaluation.get("holdout_research_gate_passed") is not False:
        raise ValueError("Missing failed holdout/research-only evidence")
    if ranking.get("model_version") != evaluation.get("model_version"):
        raise ValueError("Model versions do not match")
    coverage = audit["coverage"]
    total = sum(_int(x["universe"]) for x in coverage)
    priced = sum(_int(x["priced"]) for x in coverage)
    if total <= 0 or priced > total:
        raise ValueError("Invalid stock universe")
    latest = audit["latest"]
    price_date = latest["latest_price_date"]
    score_date = latest["latest_score_date"]
    rank_date = ranking.get("date")
    if not rank_date or rank_date != score_date:
        raise ValueError("Ranking score date does not match database score date")
    stocks = ranking.get("stocks", [])
    if ranking.get("eligible_universe", 0) < len(stocks):
        raise ValueError("Ranking larger than eligible universe")
    if not stocks:
        raise ValueError("No valid ranked research stocks")
    errors = sum(_int(audit["quality"].get(key, 0) or 0) for key in QUALITY_FIELDS)
    readiness = audit["analysis_readiness"]
    # Backlog is a distinct metric from price coverage or factor scores.
    # Fail rather than silently presenting an obsolete report without it.
    pending_rows = audit.get("indicator_backlog")
    if not isinstance(pending_rows, list) or not pending_rows:
        raise ValueError("Missing fresh indicator backlog evidence")
    totals = {"eligible": 0, "pending": 0, "complete": 0, "unstarted": 0}
    markets_seen = set()
    backlog_by_market = []
    for row in pending_rows:
        market = row.get("market")
        if market not in ("twse", "tpex") or market in markets_seen:
            raise ValueError("Indicator backlog has invalid or duplicate markets")
        markets_seen.add(market)
        item = {"market": market}
        for metric in totals:
            item[metric] = _int(row[metric])
            totals[metric] += item[metric]
        if (item["pending"] + item["complete"] != item["eligible"] or
                item["unstarted"] > item["pending"]):
            raise ValueError("Inconsistent indicator backlog counters")
        backlog_by_market.append(item)
    # 20 stocks per market per job is the current bounded processing cap;
    # this is a mathematical minimum for successful jobs, not a forecast.
    min_batches = max((item["pending"] + 19) // 20 for item in backlog_by_market)
    warnings = [
        "僅供歷史資料研究；非即時行情、買賣建議或自動交易訊號。",
        "樣本外績效未通過驗收；LINE 交易訊號與正式新閘道均未啟用。",
        "模型使用已儲存的歷史評分；不保證完全重建當時可取得資訊。",
    ]
    if price_date != score_date:
        warnings.append("最新行情日期與評分日期不同，請勿視為同日資料。")
    if errors:
        warnings.append("行情／評分資料品質條件有異常，請先排查。")
    if priced < total:
        warnings.append("並非全市場資料完全覆蓋。")
    if totals["pending"]:
        warnings.append(
            f"至少 60 日且近期有行情的股票仍有 {totals['pending']:,} 檔技術／SMC 未完整補算；"
            "行情覆蓋率不能當成模型涵蓋率。"
        )
    if generated_at is None:
        generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": 1,
        "generated_at_utc": generated_at,
        "model_version": ranking["model_version"],
        "market_date": price_date,
        "score_date": score_date,
        "candidate_stocks": total,
        "stocks_with_prices": priced,
        "price_coverage_pct": round(priced * 100 / total, 2),
        "technical_stocks": _int(readiness["technical_stocks"]),
        "smc_stocks": _int(readiness["smc_stocks"]),
        "scored_stocks": _int(readiness["scored_stocks"]),
        "history60_stocks": _int(readiness["history_60d"]),
        "history120_stocks": _int(readiness["history_120d"]),
        "history240_stocks": _int(readiness["history_240d"]),
        "quality_violations": errors,
        "indicator_backlog_by_market": backlog_by_market,
        "indicator_eligible": totals["eligible"],
        "indicator_pending": totals["pending"],
        "indicator_complete": totals["complete"],
        "indicator_unstarted": totals["unstarted"],
        "minimum_batches_at_20_per_market": min_batches,
        "research_eligible_universe": _int(ranking["eligible_universe"]),
        "research_ranked": stocks,
        "holdout_dates": _int(evaluation["holdout"]["dates"]),
        "holdout_mean_net_excess": evaluation["holdout"]["model_mean_net_excess"],
        "holdout_research_gate_passed": False,
        "research_report_available": True,
        "live_trading_approved": False,
        "line_stock_gateway_enabled": False,
        "abstain": True,
        "warnings": warnings,
    }


def markdown_report(report):
    lines = [
        "# 台股研究分析｜第一階段唯讀報告",
        "",
        f"產生時間 (UTC)：{report['generated_at_utc']}",
        f"行情日：{report['market_date']}｜評分日：{report['score_date']}",
        "",
        "| 核心資料 | 數值 |",
        "| --- | ---: |",
        f"| 有收盤行情 | {report['stocks_with_prices']:,} / {report['candidate_stocks']:,} 檔 ({report['price_coverage_pct']:.2f}%) |",
        f"| 技術指標／SMC／有效評分 | {report['technical_stocks']:,} / {report['smc_stocks']:,} / {report['scored_stocks']:,} 檔 |",
        f"| 至少 60／120／240 日歷史 | {report['history60_stocks']:,} / {report['history120_stocks']:,} / {report['history240_stocks']:,} 檔 |",
        f"| 資料品質異常條件命中 | {report['quality_violations']:,} |",
        f"| 近期且達 60 日可補指標股票 | {report['indicator_eligible']:,} 檔 |",
        f"| 技術／SMC 尚待補算 | {report['indicator_pending']:,} 檔（其中兩者都未開始 {report['indicator_unstarted']:,}） |",
        f"| 以每市場每次最多 20 檔計算的最少批次 | {report['minimum_batches_at_20_per_market']:,} 次（非完成時間預測） |",
        f"| 模型樣本外日期 | {report['holdout_dates']} |",
        f"| 樣本外平均五日超額報酬（30bp 假設成本） | {float(report['holdout_mean_net_excess'])*100:+.2f}% |",
        "",
        "## 各市場補算覆蓋",
        "",
        "| 市場 | 近期符合 60 日行情 | 待補 | 已補齊 | 兩類均未開始 |",
        "| --- | ---: | ---: | ---: | ---: |",
        *[
            f"| {item['market']} | {item['eligible']:,} | {item['pending']:,} | {item['complete']:,} | {item['unstarted']:,} |"
            for item in report["indicator_backlog_by_market"]
        ],
        "",
        "## 最新歷史研究排名（不是買賣建議）",
        f"模型：{_safe_cell(report['model_version'])}｜符合研究條件 {report['research_eligible_universe']:,} 檔",
        "",
        "| 序 | 市場 | 代碼 | 股票 | 模型相對分數 | 綜合評分 | 訊號日收盤 |",
        "| ---: | --- | --- | --- | ---: | ---: | ---: |",
    ]
    for r in report["research_ranked"]:
        lines.append(
            f"| {_int(r['rank'])} | {_safe_cell(r['market'])} | {_safe_cell(r['stock_id'])} | "
            f"{_safe_cell(r['name'])} | {float(r['relative_model_score']):+.6f} | "
            f"{float(r['raw_composite_score']):.2f} | {float(r['signal_close']):.2f} |"
        )
    lines += [
        "", "## 驗收與風險",
        "**研究報告可閱讀；交易訊號、LINE 新閘道與下單功能均未通過上線門檻。**",
    ] + [f"- {_safe_cell(s)}" for s in report["warnings"]]
    return "\n".join(lines) + "\n"


def html_report(report):
    """Standalone offline HTML; escape every database-provided stock name."""
    rows = "".join(
        "<tr>" + "".join(
            f"<td>{escape(str(v))}</td>" for v in (
                r["rank"], r["market"], r["stock_id"], r["name"],
                f"{float(r['relative_model_score']):+.6f}",
                f"{float(r['raw_composite_score']):.2f}",
                f"{float(r['signal_close']):.2f}",
            )
        ) + "</tr>"
        for r in report["research_ranked"]
    )
    warnings = "".join(f"<li>{escape(w)}</li>" for w in report["warnings"])
    def value(x):
        return escape(str(x))
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>台股研究分析｜唯讀第一階段</title>
<style>
:root{{font-family:system-ui,-apple-system,"Noto Sans TC",sans-serif;color:#202935;background:#f5f7fa}}
body{{max-width:1080px;margin:36px auto;padding:0 20px}}
h1{{font-size:1.8rem}}.muted{{color:#57657a}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px}}
.tile{{background:white;border:1px solid #dce2e9;border-radius:12px;padding:20px}}
.number{{font-size:1.8rem;font-weight:700;margin:10px 0}}
.status{{border:1px solid #b7bfc9;border-radius:10px;padding:15px;background:#fff}}
table{{width:100%;border-collapse:collapse;background:white}}th,td{{padding:11px;border-bottom:1px solid #e1e5ec;text-align:left}}th{{font-size:.88rem;color:#53627a}}
.scroll{{overflow-x:auto}}li{{margin:6px 0}}small{{color:#57657a}}
</style></head><body>
<h1>台股 AI 研究分析｜第一階段</h1>
<p class="muted">唯讀研究報告｜建立於 {value(report['generated_at_utc'])}<br>
行情日 {value(report['market_date'])}，評分日 {value(report['score_date'])}。不是即時行情。</p>
<div class="status"><strong>研究模型已建置；交易訊號停用</strong>
<p>樣本外結果未通過績效驗收。此頁不是推薦買賣、下單系統或正式 LINE 新閘道。</p></div>
<h2>資料狀態</h2><div class="grid">
<div class="tile">有效行情<div class="number">{report['stocks_with_prices']:,} / {report['candidate_stocks']:,}</div><small>覆蓋 {report['price_coverage_pct']:.2f}%</small></div>
<div class="tile">已評分股票<div class="number">{report['scored_stocks']:,}</div><small>技術 {report['technical_stocks']:,}、SMC {report['smc_stocks']:,}</small></div>
<div class="tile">60／120／240 日<div class="number">{report['history60_stocks']:,} / {report['history120_stocks']:,} / {report['history240_stocks']:,}</div><small>真實交易日歷史檔數</small></div>
<div class="tile">待補技術／SMC<div class="number">{report['indicator_pending']:,} / {report['indicator_eligible']:,}</div><small>兩類都未開始 {report['indicator_unstarted']:,} 檔；最少 {report['minimum_batches_at_20_per_market']:,} 批次（非時程）</small></div>
<div class="tile">研究樣本外超額<div class="number">{float(report['holdout_mean_net_excess'])*100:+.2f}%</div><small>每組五日、30bps 假設成本，非策略績效</small></div>
</div>
<h2>最新歷史研究排名</h2>
<p class="muted">模型 {value(report['model_version'])}，合格股票 {report['research_eligible_universe']:,} 檔；不代表買入優先順序。</p>
<div class="scroll"><table><thead><tr><th>序</th><th>市場</th><th>代碼</th><th>名稱</th><th>相對分數</th><th>綜合分數</th><th>歷史收盤</th></tr></thead><tbody>{rows}</tbody></table></div>
<h2>風險與限制</h2><ul>{warnings}</ul>
<p><small>READ-ONLY · abstain=true · live_trading_approved=false · 無訊息發送</small></p>
</body></html>
"""


def main():
    p = argparse.ArgumentParser(description="Render offline, fail-closed stock research snapshot")
    p.add_argument("--audit", type=Path, required=True)
    p.add_argument("--ranking", type=Path, required=True)
    p.add_argument("--evaluation", type=Path, required=True)
    p.add_argument("--outdir", type=Path, required=True)
    args = p.parse_args()
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    ranking = json.loads(args.ranking.read_text(encoding="utf-8"))
    evaluation = json.loads(args.evaluation.read_text(encoding="utf-8"))
    report = build_summary(audit, ranking, evaluation)
    args.outdir.mkdir(parents=True, exist_ok=True)
    (args.outdir / "research-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    markdown = markdown_report(report)
    (args.outdir / "research-report.md").write_text(markdown, encoding="utf-8")
    (args.outdir / "research-report.html").write_text(html_report(report), encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write(markdown)
    print(f"Research-only report written; {report['research_eligible_universe']} eligible, "
          f"score date {report['score_date']}, trading disabled.")


if __name__ == "__main__":
    main()
