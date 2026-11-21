"""Bounded retrospective *actual label* readiness gate for Taiwanese equities.

Never confuse 100% of latest scored stocks with enough historically comparable
forward return periods to validate a trading model. This helper only reads
aggregate daily label completeness (not raw database credentials or individual
signals), and never fits, changes or promotes the saved investment model.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re

MAX_DAYS = 120
MIN_COHORT = 10
MIN_INDEPENDENT_WINDOWS = 10
MIN_COVERED_CALENDAR_DAYS = 60

# Exactly the existing trained model label semantics:
# signal t, entry t+1 raw trading session, exit t+6 raw trading session.
# The adjusted prices must exist on all three required sessions, and the
# forward label may only be assessed after its actual exit session.
DAILY_LABEL_SQL = """
WITH sessions AS (
 SELECT p.market,p.stock_id,p.trade_date,a.close AS signal_adjusted,
        LEAD(p.trade_date,1) OVER w AS entry_date,
        LEAD(a.close,1) OVER w AS entry_adjusted,
        LEAD(p.trade_date,6) OVER w AS exit_date,
        LEAD(a.close,6) OVER w AS exit_adjusted
 FROM public.daily_prices p
 LEFT JOIN public.daily_adjusted_prices a
   ON a.market=p.market AND a.stock_id=p.stock_id
  AND a.trade_date=p.trade_date
 WHERE p.close>0
 WINDOW w AS (PARTITION BY p.market,p.stock_id ORDER BY p.trade_date)
), labeled AS (
 SELECT s.as_of_date AS signal_date,
        (sess.signal_adjusted>0 AND sess.entry_adjusted>0 AND
         sess.exit_adjusted>0 AND
         sess.entry_date>s.as_of_date AND
         sess.exit_date>sess.entry_date AND sess.exit_date<=%s) AS usable,
        sess.entry_date, sess.exit_date
 FROM public.daily_composite_scores s
 LEFT JOIN sessions sess ON sess.market=s.market
   AND sess.stock_id=s.stock_id AND sess.trade_date=s.as_of_date
 WHERE s.as_of_date BETWEEN %s AND %s
   AND s.total_score IS NOT NULL AND s.stock_id<>'1808'
)
SELECT signal_date,COUNT(*)::int AS scored,
       COUNT(*) FILTER(WHERE usable IS TRUE)::int AS mature,
       COUNT(DISTINCT entry_date) FILTER(WHERE usable IS TRUE)::int AS distinct_entries,
       COUNT(DISTINCT exit_date) FILTER(WHERE usable IS TRUE)::int AS distinct_exits,
       MIN(entry_date) FILTER(WHERE usable IS TRUE) AS first_entry,
       MAX(entry_date) FILTER(WHERE usable IS TRUE) AS last_entry,
       MIN(exit_date) FILTER(WHERE usable IS TRUE) AS first_exit,
       MAX(exit_date) FILTER(WHERE usable IS TRUE) AS last_exit
FROM labeled
GROUP BY signal_date ORDER BY signal_date
LIMIT 121
"""


def _day(value):
    if isinstance(value, datetime):
        raise ValueError("Trade day must not be a timestamp")
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Exact research YYYY-MM-DD date required")
    return date.fromisoformat(value).isoformat()


def _count(raw, name):
    value = raw.get(name)
    if type(value) is not int or value<0:
        raise ValueError("Missing nonnegative verified aggregate: " + name)
    return value


def _validated_row(raw, *, start, end, cutoff):
    if not isinstance(raw, dict):
        raise ValueError("Each day must be a verified aggregate object")
    signal=_day(raw.get("signal_date"))
    if not start<=signal<=end<=cutoff:
        raise ValueError("Signal outside bounded research window")
    scored=_count(raw,"scored")
    mature=_count(raw,"mature")
    entries=_count(raw,"distinct_entries")
    exits=_count(raw,"distinct_exits")
    if scored<=0 or mature>scored or entries>mature or exits>mature:
        raise ValueError("Inconsistent historically scored and matured counts")
    date_fields={}
    for field in ("first_entry","last_entry","first_exit","last_exit"):
        date_fields[field]=_day(raw[field]) if raw.get(field) is not None else None
    if mature==0 and (entries or exits or any(date_fields.values())):
        raise ValueError("Unmatured cohort cannot have a validated holding window")
    if mature>0:
        if not all(date_fields.values()) or entries<1 or exits<1:
            raise ValueError("Mature labels require exact actual holding window dates")
        if not (signal<date_fields["first_entry"]<=date_fields["last_entry"]
                <date_fields["first_exit"]<=date_fields["last_exit"]<=cutoff):
            raise ValueError("Malformed or future-dated adjusted holding periods")
        if entries==1 and date_fields["first_entry"]!=date_fields["last_entry"]:
            raise ValueError("One entry date cannot have distinct observed bounds")
        if exits==1 and date_fields["first_exit"]!=date_fields["last_exit"]:
            raise ValueError("One exit date cannot have distinct observed bounds")
    return {"signal_date":signal,"scored":scored,"mature":mature,
            "distinct_entries":entries,"distinct_exits":exits,**date_fields}


def assess_historical_labels(rows, *, start, end, cutoff,
                             min_cohort=MIN_COHORT,
                             min_independent=MIN_INDEPENDENT_WINDOWS,
                             source="OFFLINE_USER_SUPPLIED_UNVERIFIED"):
    """Determine if as-of-labeled history is large enough even to evaluate.

    All comparisons are on *whole signal-date cohorts*; never keep only the
    tickers with known positive adjusted forward labels. Entry/exit calendars
    must be identical across the entire included cohort.
    """
    start,end,cutoff=map(_day,(start,end,cutoff))
    if not start<=end<=cutoff or (date.fromisoformat(end)-date.fromisoformat(start)).days>MAX_DAYS:
        raise ValueError("Research window/cutoff invalid or too broad")
    if type(min_cohort) is not int or not 5<=min_cohort<=100:
        raise ValueError("Minimum cohort size must be 5..100")
    if type(min_independent) is not int or not 5<=min_independent<=50:
        raise ValueError("Minimum independent windows must be 5..50")
    if not isinstance(rows,list) or len(rows)>MAX_DAYS:
        raise ValueError("Historical data must have at most 120 daily summaries")
    records=sorted((_validated_row(r,start=start,end=end,cutoff=cutoff) for r in rows),
                   key=lambda r:r["signal_date"])
    if len({r["signal_date"] for r in records})!=len(records):
        raise ValueError("Duplicate signal-date summaries")
    counts=Counter()
    accepted=[]
    for row in records:
        if row["scored"]<min_cohort:
            status="INSUFFICIENT_ORIGINAL_SCORED_COHORT"
        elif row["mature"]!=row["scored"]:
            status="INCOMPLETE_OR_UNMATURED_FORWARD_LABELS"
        elif row["distinct_entries"]!=1 or row["distinct_exits"]!=1:
            status="UNMATCHED_ACTUAL_ENTRY_OR_EXIT_DATES"
        else:
            status="COMPLETE_HOLDING_WINDOW"
            accepted.append(row)
        counts[status]+=1
    selected=[]
    last_exit=None
    for row in accepted:
        day=row["signal_date"]
        if last_exit is not None and day<=last_exit:
            counts["OVERLAPS_PREVIOUS_SELECTED_EXIT"]+=1
            continue
        selected.append(row)
        last_exit=row["last_exit"]
    span=(date.fromisoformat(selected[-1]["signal_date"])-
          date.fromisoformat(selected[0]["signal_date"])).days if len(selected)>1 else 0
    enough=(len(selected)>=min_independent and span>=MIN_COVERED_CALENDAR_DAYS)
    payload=json.dumps(records,sort_keys=True,separators=(",",":"),
                       ensure_ascii=True,allow_nan=False)
    return {
        "schema_version":1,"source":source,
        "start":start,"end":end,"known_label_cutoff":cutoff,
        "date_summary_sha256":sha256(payload.encode("utf-8")).hexdigest(),
        "scored_signal_dates":len(records),
        "scored_signal_rows":sum(row["scored"] for row in records),
        "mature_forward_rows":sum(row["mature"] for row in records),
        "status_counts":{key:counts[key] for key in (
            "INSUFFICIENT_ORIGINAL_SCORED_COHORT",
            "INCOMPLETE_OR_UNMATURED_FORWARD_LABELS",
            "UNMATCHED_ACTUAL_ENTRY_OR_EXIT_DATES",
            "COMPLETE_HOLDING_WINDOW",
            "OVERLAPS_PREVIOUS_SELECTED_EXIT"
        )},
        "fully_labeled_aligned_dates":len(accepted),
        "nonoverlapping_actual_holding_windows":len(selected),
        "nonoverlapping_signal_span_days":span,
        "minimum_required_nonoverlapping_windows":min_independent,
        "minimum_required_signal_span_days":MIN_COVERED_CALENDAR_DAYS,
        "eligible_for_exploratory_outcome_research":enough,
        "model_alpha_approved":False,
        "previous_model_holdout_not_independent":True,
        "market_wide_survivorship_bias_audited":False,
        "corporate_action_adjustment_vintage_verified":False,
        "data_scope":"existing_historical_scored_cohorts_not_1991_stock_universe",
        "database_writes":False,
        "line_signals_enabled":False,
        "orders_enabled":False,
        "selected_signal_dates":[r["signal_date"] for r in selected],
    }


def readonly_aggregate(url, *, start, end, cutoff):
    if not url or os.environ.get("HISTORICAL_RESEARCH_LABEL_READONLY")!="yes":
        raise PermissionError("Explicit protected read-only Neon opt-in required")
    start,end,cutoff=map(_day,(start,end,cutoff))
    if not start<=end<=cutoff or (date.fromisoformat(end)-date.fromisoformat(start)).days>MAX_DAYS:
        raise ValueError("Bounded read-only historical window required")
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(url,connect_timeout=10,row_factory=dict_row,
                         options="-c default_transaction_read_only=on") as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cur.execute("SET LOCAL statement_timeout = '20000ms'")
                cur.execute(DAILY_LABEL_SQL,(cutoff,start,end))
                result=[dict(x) for x in cur.fetchmany(MAX_DAYS+1)]
                if len(result)>MAX_DAYS:
                    raise ValueError("Unbounded historical signal-date output")
    return result


def render_markdown(report):
    return "\n".join([
        "# 實際歷史標籤成熟度檢查（非可交易投資回測）","",
        f"- 來源：{report['source']}",
        f"- 訊號期間：{report['start']} 至 {report['end']}",
        f"- 以 {report['known_label_cutoff']} 前已知未來報酬為限。",
        f"- 歷史有評分訊號日：{report['scored_signal_dates']}",
        f"- 完整且持有日期一致：{report['fully_labeled_aligned_dates']}",
        f"- 排除重疊後獨立觀察窗：{report['nonoverlapping_actual_holding_windows']}",
        f"- 需至少 {report['minimum_required_nonoverlapping_windows']} 個窗與 "
        f"{report['minimum_required_signal_span_days']} 日曆日跨度。",
        f"- 是否具備探索性驗證的最小觀察量：{'是' if report['eligible_for_exploratory_outcome_research'] else '否'}",
        "- 這不是新模型回測績效，也不會修正此前失敗的舊 holdout。",
        "- 訊號股票池存在樣本選擇偏差，公司行動重算歷史可能改變成果。",
        "- Neon 沒有資料寫入，沒有 LINE 或交易指令。",
        "",
        "## 每個訊號日的主要排除原因",
        "",
        *[f"- {name}: {n}" for name,n in report["status_counts"].items()],
        "",
    ])


def main():
    import argparse
    p=argparse.ArgumentParser(description="As-known historical labels, research only")
    modes=p.add_mutually_exclusive_group(required=True)
    modes.add_argument("--source-json",type=Path)
    modes.add_argument("--read-neon",action="store_true")
    p.add_argument("--start",type=date.fromisoformat,required=True)
    p.add_argument("--end",type=date.fromisoformat,required=True)
    p.add_argument("--cutoff",type=date.fromisoformat,required=True)
    p.add_argument("--output-json",type=Path,required=True)
    p.add_argument("--output-md",type=Path,required=True)
    args=p.parse_args()
    if args.read_neon:
        rows=readonly_aggregate(os.environ.get("DATABASE_URL",""),
                                start=args.start,end=args.end,cutoff=args.cutoff)
        source="NEON_CURRENT_SCORED_COHORT_READONLY_NOT_ASOF_VINTAGE_PROVEN"
    else:
        rows=json.loads(args.source_json.read_text(encoding="utf-8"))
        source="OFFLINE_USER_SUPPLIED_UNVERIFIED"
    report=assess_historical_labels(rows,start=args.start,end=args.end,cutoff=args.cutoff,source=source)
    for file,content in (
        (args.output_json,json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n"),
        (args.output_md,render_markdown(report)),
    ):
        file.parent.mkdir(parents=True,exist_ok=True)
        file.write_text(content,encoding="utf-8")
    print(json.dumps({"eligible_for_exploratory_outcome_research":
                      report["eligible_for_exploratory_outcome_research"],
                      "nonoverlapping_actual_holding_windows":
                      report["nonoverlapping_actual_holding_windows"],
                      "model_alpha_approved":False},ensure_ascii=False))


if __name__=="__main__":
    main()
