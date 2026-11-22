# Storage-free verification of missing TWSE 2022 official market sessions

**Research-only experiment** supporting the five-year capacity bottleneck #176.

The original five-year campaign stores daily MI_INDEX official market data in
Neon and is approaching the existing protected 800MB ceiling with a 50MB
maintenance margin. For data older than existing imported sessions, we can
investigate fetching dated official sources directly when needed, without
creating permanent Neon price/index rows. This is currently just a two-date
feasibility probe; no five-year model or factor coverage is being claimed.

The main-only job probes January 4 and January 5, 2022 through the
same fetch_official_day function and date-validating parser used by the
approved history backfill. A protected REPEATABLE READ READ ONLY Neon
transaction loads the newest verified current-listed issuer roster and owner
model exclusions (including 1589), and confirms neither requested date has
already been marked imported or closed. The REST responses stay in runner RAM,
are filtered to currently eligible securities, date-checked, deduplicated,
minimum-coverage checked, and hashed exactly using source DECIMAL text.
The published artifact has **only** trade dates, aggregate eligible bar counts,
content SHA-256 fingerprints and explicit non-release flags.

The job does **not** write raw source rows, gzip data, or extra prices to
GitHub or Neon; it sends no LINE messages. The source service gets at most two
official requests with an interval. Any exchange HTTP failure, unrecognized
trading session, incomplete eligible issuer coverage, date mismatch or quota
condition fails the probe rather than inventing results.

**Important limitations:** Historic raw-price fetchability is not verified
five-year completeness; the selected stock list is the *current* issuer
survivor population and is not historically free of survivorship bias.
Official corporate-action vintages, historical factor consistency, truly
untouched future validation and real trading profitability remain unproven.
Do not use this experiment to release trading picks or to delete existing
Neon data. Even if the two-day probe succeeds, full-scale streaming replay
would require a separate bounded design, real request-budget studies,
caching/privacy review and independent tests before any implementation.
