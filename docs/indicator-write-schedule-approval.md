# Independent indicator catch-up WRITE schedule — approval proposal only

**Draft only. Do not merge until authorized.** This changes when the
production `twstock` database receives indicator writes; unlike
`indicator-schedule-probe.yml`, this is not a read-only workflow.

## Why the replacement is needed

The prior `feature/indicator-schedule-reliability-20261120` PR #15
was based on an older `main` and is now conflicted. It proposed adding
an independent cron while retaining the upstream `workflow_run` trigger.
That combination can run **two write batches in the same day**: concurrency
ensures serial execution but does not deduplicate completed jobs.

This proposal instead uses exactly **one schedule event** per Taiwan
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

## Pre-merge decision record

The current baseline observed on 2026-11-20: **TWSE 1,044 pending,
41 complete, 942 unstarted; TPEx 0 pending and 21 complete**.
If 20 listed symbols are completed per successful scheduled run,
the mathematical minimum is 53 such runs. This is not a promise or
an estimate of calendar completion, as source data and eligibility change.

Before merging this draft, the operator must separately approve the new
**automatic production write schedule**, ensure database write/compute
budget is acceptable, review the prior PR #15 supersession, and confirm
failure alerts and rollback plan. After merging, a scheduled run must
show real before/after coverage improvement and persisted post-write
counts; test PASS alone is not evidence of backfill.
