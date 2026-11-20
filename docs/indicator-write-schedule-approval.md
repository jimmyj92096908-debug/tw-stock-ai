# Authorized independent indicator catch-up WRITE schedule

**Approved and merged to `main` in PR #26 on 2026-11-20.** This workflow writes
verified adjusted prices, technical indicators and SMC to production `twstock`,
subject to the existing 20-per-market cap and per-stock savepoint rollback.
The independent `indicator-schedule-probe.yml` remains strictly read-only.

## Why the replacement is needed

The prior `feature/indicator-schedule-reliability-20261120` PR #15
was based on an older `main` and is now conflicted. It proposed adding
an independent cron while retaining the upstream `workflow_run` trigger.
That combination can run **two write batches in the same day**: concurrency
ensures serial execution but does not deduplicate completed jobs.

The activated workflow uses exactly **one schedule event** per Taiwan
Tue–Sat at 03:10, after the 01:50 scheduled dated-history import.
Manual `workflow_dispatch apply=false` is preview only.
Manual `apply=true` is a separate explicit operator action.
The workflow is guarded to the expected repository and `main` branch.

The already merged `indicator-schedule-probe.yml` runs read-only at
03:05 and can prove GitHub Actions cron and Neon access without writes.
For evidence before a production change, inspect that probe's first
`push` execution and at least one genuine `schedule` execution.
A successful push event does **not** establish cron reliability.

## Limits and safety

- A bounded WRITE batch processes at most **20 TWSE and 20 TPEx stocks**
  per scheduled invocation. It only selects fresh (last close within seven
  days of the current database latest) stocks with at least **60 genuine
  non-null price sessions**, excluding 1808.
- Each stock's adjusted, technical and SMC operations are now enclosed
  in a PostgreSQL SAVEPOINT (merged PR #23). A failed symbol's writes
  roll back while others may commit. Any failed symbol makes the process
  exit nonzero; a failing job does not trigger successful-score refresh.
- After both read-only snapshots are recorded, the standalone
  `scripts/indicator_batch_reconcile.py` (safely merged to `main` via
  PR #27) independently checks each market's eligible, pending and
  complete counts. A pending market must show a real decrease in pending
  stocks and matching increase in completed stocks; a date or universe
  change is inconclusive and fails closed. Any failed proof stops a
  scheduled job before it can trigger composite scoring.
- An isolated PostgreSQL 17 integration test now exercises the actual
  **20-stock** batch with **60 rows of dummy adjusted, technical and SMC
  records per stock (1,200 per table)**, plus the existing real SQL
  error/savepoint rollback test. No production Neon data is written.
- Before the batch, `scripts/indicator_schedule_probe.py` runs a
  PostgreSQL REPEATABLE READ READ ONLY snapshot and saves
  `indicator-before.json`. After the batch, it runs again to save
  `indicator-after.json` even if the batch fails. Both reports are
  aggregate-only and retained as a 14-day GitHub artifact.
- The downstream `Composite Scores After Verified Official Snapshot`
  workflow is allowed to respond **only to a successful scheduled**
  indicator catch-up (plus its already-authorized daily source snapshot).
  It does not respond to a manual dry-run. Manual indicator apply must
  receive separately authorized composite score refresh.
- All new writes remain behind `--apply` and
  `STOCK_INDICATOR_CATCHUP_WRITE_ENABLED=yes`. No LINE or trading
  functionality is introduced.

## Approval and verified first production execution

The owner explicitly authorized activation on 2026-11-20. PR #26 was merged,
and the one-time bounded two-stock-per-market real Neon pilot (PR #28)
completed successfully: [Actions #44720719864](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44720719864).
TWSE pending **1,044 → 1,042**, complete **41 → 43**, unstarted **942 → 940**.
TPEx stayed 0 pending of 21 eligible.

A separately authorized use of the existing composite score runner confirmed
both newly completed TWSE stocks 1626 and 1702 received valid same-day scores:
[Actions #44722651205](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/44722651205).
Valid composite-scored symbols grew **164 → 166**. Both temporary one-shot
activation workflows are retired after success; historical artifacts remain.

**The recurring 03:10 schedule is enabled but no real scheduled indicator
execution has yet been observed after this activation.** Its first real cron
run still requires the before/after Neon checks and a successful downstream
composite-score workflow run. Do not treat an initial one-shot pilot as proof
of unattended recurring reliability. At a maximum of 20 TWSE symbols per
successful scheduled run, 1,042 pending stocks imply a mathematical minimum
of 53 more full-success batches if the universe stays fixed; this is not a
calendar forecast. No LINE webhook cutover or trade signal is approved.
