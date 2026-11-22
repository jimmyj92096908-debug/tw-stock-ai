# 2022 TWSE shared-source 48-session bounded live pilot

**Status:** Research canary only; no Neon data migration, model alpha approval
or 240-session historical backfill claims.

The verified 12-day whole-market stream is extended to a maximum of **48
separately verified official trading dates**, January 4 through March 22,
2022. Dates come from an existing 2330 `TWSE_STOCK_DAY` date calendar in
Neon under a transaction set explicitly to READ ONLY. The 48-source-date
plan includes no Taiwan Lunar New Year nontrading dates (the calendar skips
Jan 27–Feb 6, 2022) and excludes February 28. It is not a replacement for
checking official as-of issuer membership.

Every official date gets **one** identical date-qualified TWSE
`MI_INDEX?type=ALLBUT0999` request, with a fixed **four-second interval**,
strictly no automatic retries or dynamic URL/extra request inputs. Original
source JSON and all price bars stay in ephemeral runner memory. The existing
current-listed issuer allowlist, user exclusion registry including 1589,
coverage minimum, exact numeric and quote date checks must all pass.
Any error stops the whole job without emitting a success report.

A successful full run reports only daily eligible **counts**, number of
currently surviving listed stocks continuously covered, a hash and the
**descriptive** raw-price change distribution. It does NOT emit any market
price row, per-stock feature, stock pick or historical archive. Neither Neon
nor the LINE webhook is modified.

GitHub's official billing documentation confirms ordinary Ubuntu-hosted
Actions runners in **public repositories** are free; this workflow uses one
such standard runner and uploads **no artifact** (tiny aggregate evidence
is printed to logs only). There is no schedule or workflow_dispatch. It
is triggered once on the reviewed main-branch code push. If the original
source declines or throttles this test, fail closed rather than bypassing
source rate restrictions or triggering bulk automatic repeats.

**Crucial:** a 48-day observation still cannot warm up a 240-day moving
average, technical factor model or market-wide five-year model. An earlier
241-date/650-stock stress test used **synthetic** dates and prices.
Before any longer real-market replay, audit source reliability and request
policy, storage and transient memory limits, issuer survivorship, corporate
actions, old-source capture vintage and true untouched forward validation.
Even strong technical tests do not override the existing blocked live-trade
model gate.
