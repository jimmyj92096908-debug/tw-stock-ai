# Gated 2022 real-market 241-session raw MA240 proof (no Neon storage)

**Research-only.** Existing old TWSE MI_INDEX source tests successfully
fetched first 48 2022 trading sessions (Jan 4–Mar 22) and then separately
verified session ordinals 49–96 (Mar 23–Jun 1), with fixed four-second
source intervals and no price/factor database writes. Each short test
retains source rows only in runner memory, so it cannot by itself form
a cross-run continuous MA240 data series.

This new workflow runs a **single bounded 241-session replay** using a
prior-extracted TWSE 2330 official STOCK_DAY trading-date calendar for
2022 Jan 4 through Dec 26. Its 241-date list is frozen with a SHA256
computed from Neon and accepted only when it exactly matches the
read-only current database calendar; a holiday, missing date or unexpected
extra date fails before ANY HTTP call.

The official current-listed issuer snapshot must be fresh and the model
exclusion registry must exclude 1589. Each of the 241 sessions invokes at
most **one dated TWSE MI_INDEX full-market HTTP GET**, with a four-second
minimum pause between calls, no automatic retries, no user-controlled
request count and no concurrent overlapping 48-day source workflow.
Results are validated as the correct official trade date and exact OHLCV
values. The existing stream processor computes exact Decimal MA240 and
previous-day parity for **every** currently surviving stock continuously
observed for all 241 dates, plus five existing 12-feature technical/SMC
previous-day causality checks. At least 500 complete stocks are required.

Only aggregate issuer counts, official dates, a content SHA256 and strong
non-release flags are written to short-lived GitHub job logs; raw source
bars, issuer-level features and model weights stay in memory and are never
uploaded, persisted in Neon or sent to LINE.

**Significant limits:** Even successful real 2022 source-on-demand replay
proves one 241-session *price-only* MA240 cohort, **not** five-year
historical coverage or price/source-vintage completeness. The issuer
universe is current survivors, not necessarily all issuers that existed
in 2022; delisted companies and 1589 remain excluded by owner direction.
Unadjusted price factors do not equal dividend-adjusted investment
returns. No corporate-action factors, announcement as-of timestamps,
pristine forward alpha, live trading signals or cash-flow impact are
verified. The separate 2024 894-stock corporate-action coverage audit
reported zero 2024 verified event and adjusted price rows *within that
specific clean full-year cohort*. Do not retrain or release an actual
total-return model on these incomplete labels.

Workload is one time only on reviewed main code. It uses a standard
public-repo Ubuntu GitHub Actions runner with no additional charge,
max 38 minutes and a one-shot source request cap; any failed official
day halts the full proof instead of producing fake counts or retrying
a potentially rate-limited API. The code never modifies production Neon,
LINE, stored factor scores or branch permissions.
