# 2024 full current-listed TWSE MA240 cross-section: read-only benchmark

Research-only capacity alternative under Issue #176.

A previous five-stock saved-source benchmark successfully reused one shared
TWSE 2024 242-date official daily source panel. A read-only production SQL
audit on 2026-11-22 observed **894** currently officially listed and
owner-allowed securities with all 242 saved 2024 market dates and basic
price-quality checks. This is NOT confirmation of all past 2022 sessions.

The new implementation reads the 2024 official `MI_INDEX_ALLBUT0999`
source for exactly these eligible still-current issuers through **one
READ ONLY PostgreSQL server-side cursor**. It only admits stocks with 242
actual exchange source rows, all exact positive Decimal OHLC and valid
nonnegative share counts, and excludes both delisted-current issuers
and 1589 via the fresh official listing and owner exclusion registry.
The in-memory auditing function keeps at most 242 rows for the current
stock and checks that every accepted issuer shares the same 242 dates.

For **every** admitted issuer, it computes an exact 240-source-session
closing-price SMA at the last saved date and previous session, proving
previous SMA cannot change upon seeing the next day's bar. For the
first five continuously observed stocks, it also computes the existing
12-feature technical/SMC vector and repeats the previous-day prefix
no-future-leakage comparison. Only cohort totals, SHA256, date range,
MA240 and technical/SMC verification counts are logged. The code never
writes source rows, financial output rows, composite scores or archives,
never sends LINE, and never issues real or hypothetical orders.

No live exchange HTTP requests are made by this benchmark; the 2024\nmarket quotes were already sourced and validated in Neon. This avoids\ncompeting for TWSE source bandwidth with the separate 2022 replay.\n\nThe workflow requires green offline CI before real main-branch read-only
execution and uses a standard free GitHub Actions runner without
uploaded artifacts. It is separate from the **2022 historical HTTP
request pilot**, so two different verification dimensions remain clear:
2024 cross-sectional algorithm/source availability versus 2022 missing
source-on-demand replay.

**Release blockers:** This verifies current surviving issuers over one
past calendar year, not a point-in-time universe with delisted firms.
The model does not yet have five-year unbroken per-stock history,
complete dividend/corporate-action adjustments, independent vintage
capture proof, or positive pristine forward cost-stressed holdout
performance. No live AI investment signals may be published.
