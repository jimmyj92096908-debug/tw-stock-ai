# TWSE official historical importer: early Neon Free storage preflight (2026-11-24)

## Root cause and exact evidence

The scheduled **TWSE Dated Bulk Historical Price Backfill** run [#45240575342](https://github.com/jimmyj92096908-debug/tw-stock-ai/actions/runs/45240575342) failed while attempting authorized historical import: `RuntimeError: TWSE official source import blocked by Neon Free storage reserve`. The parser/source-preview and original isolated tests passed first, so the workflow consumed official preview/network and runner time before encountering the already known storage block. This is a **correct safety block**, not a request to raise the capacity limit.

Earlier verified read-only Neon snapshot on 2026-11-24: `pg_database_size(current_database()) = 753,147,904` bytes. The existing conservative TWSE source write admission requires **strictly**:

```text
database_bytes + 50,000,000 maintenance-reserve
               + (source_days × 1,500 max official rows/day × 600 stress bytes/row)
    < 800,000,000 bytes.
```

For one official source date the absolute maximum *starting* database size is **less than 749,100,000 bytes**. Thus the prior 753,147,904-byte snapshot already exceeds one-day safe admission by 4,047,904 bytes. That does **not** measure Neon billing/egress/compute, reclaimable physical bytes, or the number of missing historical stock-date keys. Do not compare separate logical and physical accounting as interchangeable. A snapshot can age; the new read-only check uses an actual live database size each time.

## Exact changes and safety

1. Adds `python src/twse_dated_history.py --preflight`. This makes a new PostgreSQL connection with `default_transaction_read_only=on`, runs a short `REPEATABLE READ, READ ONLY` transaction with 6-second statement timeout, and reads **only** `pg_database_size(current_database())`. It performs no official HTTP, Neon DML/DDL, LINE message, model inference, or billing API. If one-day headroom is absent, it prints aggregate `ABSTAIN_STORAGE_RESERVE` and exits **nonzero**; it does not mark blocked historical work as success or claim another date was imported.
2. The authorized scheduled importer workflow invokes this *before* the official source preview; manual `workflow_dispatch` with `apply=false` retains the existing preview-only behavior. Missing credentials, invalid DB size and connection failure are fail-closed rather than bypasses.
3. The existing import function checks storage **before attempting even `CREATE TABLE IF NOT EXISTS`** for its progress table, and **rechecks for each source date** before applying actual price insertion. Import conditions, source parser, listing allowlist, exclusions (including 1589), append-only uniqueness, and 1–8-day request limits remain unchanged.
4. New deterministic generated-boundary tests compare the implementation to **separately specified arithmetic**; mocked read-only connection tests assert that the query sequence has no writes, no source HTTP and no exposed secret. A dedicated no-Neon GitHub CI executes the new tests twice and existing historical source tests. This is not evidence of production data coverage.

## Clear separation of acceptance

- `OFFLINE_PRECHECK_PASS` = the guard and workflow order were exercised in CI, not that Neon has enough capacity.
- `PRODUCTION_STORAGE_ADMISSION` = requires a *fresh live read-only* measurement plus the existing per-date apply guard and explicit write permission. A passing preflight does not itself authorize the apply operation.
- `FIVE_YEAR_HISTORY_COMPLETE` = **FALSE** until every intended valid stock/date has official source provenance, complete company actions, and independent PIT evidence.
- `MODEL_RELEASE` = **BLOCKED**; existing negative/non-pristine model holdout and historical survivorship/total-return blockers remain.
- No paid upgrade, raising capacity limits, deletion of used indexes/derived factors, private archive publication, LINE change, or trades are permitted by this work.

## Why this is not a storage fix

The patch stops futile scheduled HTTP before an already inevitable refusal. It does not free bytes, delete anything, perform five-year backfill, authorize migration, or make the research model profitable. The long-term capacity work remains tracked in [issue #176](https://github.com/jimmyj92096908-debug/tw-stock-ai/issues/176): a verified private encrypted archive/index + reversible restore and separate capacity/coverage audit under independent review, without increasing cost or modifying LINE.
