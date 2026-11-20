# Indicator catch-up cron preflight (read-only)

The unresolved gap is **1,044 recent TWSE stocks with >=60 verified closing
sessions pending technical/SMC** as observed with a live read-only Neon query
on 2026-11-20. Of those, 942 have neither technical nor SMC history. The
corresponding eligible TPEx cohort (21 stocks) is complete.

The existing indicator catch-up runs after the scheduled TWSE dated-history
workflow via GitHub workflow_run. GitHub Actions places limits on chained
workflows, and no real scheduled indicator catch-up execution was located in
the inspected recent schedule runs. **Absence in the observed run list is not
proof of why the job did not execute.** Do not claim the code fixed upstream
schedules or that data has been backfilled.

## What this independently scheduled probe does

- Every Tuesday–Saturday at **03:05 Asia/Taipei** (cron `5 19 * * 1-5`
  UTC), use its own GitHub schedule and concurrency group. The independent
  schedule is a non-writing preflight, not a replacement for the guarded
  indicator catch-up job.
- On push to main, also run once immediately to capture a real baseline.
- Install existing dependencies and run all offline regression tests first.
- Connect to the existing protected `DATABASE_URL`, open one PostgreSQL
  `REPEATABLE READ READ ONLY` transaction, execute the existing aggregate
  audit and unchanged per-market bounded `select_candidates` SQL.
- Reject inconsistent market totals, invalid or repeated candidates, an
  empty current-price date, or a preview that differs from the first
  `min(pending,20)` eligible stocks per market.
- Produce `indicator-schedule-probe.json` and an aggregate GitHub Actions
  Summary. The JSON has no database credentials, private messages or
  stock-level rankings; stock codes are verified in memory but **not** exported.
- Emit `indicator_writes_performed=false`,
  `automatic_write_schedule_activated=false` and
  `trading_signals_enabled=false`, regardless of the result.

## How to inspect

Open [Indicator Catch-Up Schedule Probe (Read-Only)](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/workflows/indicator-schedule-probe.yml)
and select a successful execution on `main`. Inspect Summary and download
`indicator-schedule-readonly-probe` under Artifacts. Its run time is evidence
of cron firing, and the counts are evidence only of *remaining backlog*.

At 20 TWSE stocks per successful **write-enabled** indicator run, the
current 1,044 pending stocks imply at least `ceil(1044/20) = 53` successful
runs *if the eligible universe never changes and every run succeeds*. This
is not a scheduling promise or a forecast.

## Not yet done

The original independent **write-enabled** schedule proposal is still
unmerged/conflicted in PR #15. Enabling that on the production database is a
separate operational approval; it can increase database writes and affects
the downstream composite score refresh. No production write schedule is
enabled by this preflight. Separately, live LINE user E2E and the candidate
gateway's two missing protected credentials remain outstanding; none of
those requirements are affected here.
