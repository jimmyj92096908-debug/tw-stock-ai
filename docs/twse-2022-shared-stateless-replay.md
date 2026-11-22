# Replaying archived 2022 TWSE market dates without Neon storage

This is an intentionally bounded feasibility bridge between existing
**real** 2022 MI_INDEX 5-day source research and **real** shared 2024 five-stock
MA240 research.

The owner-protected GitHub main-only job reads exactly **12** archived
2022 trading-date references for 2330 from Neon via READ ONLY transaction;
they are a convenient date calendar, **not** certification that 2022 full
market data exist in Neon. Each date is independently validated against one
whole-market TWSE `MI_INDEX?type=ALLBUT0999` source request. Request count
cannot be raised via workflow inputs; an exchange failure does not cause
automatic unbounded retries. Each pair of requests waits two seconds.

The official source decoder validates the *claimed trade date*, real
Decimal OHLCV and duplicate security/date keys. We intersect the current,
fresh, official TWSE listed issuer registry with model owner exclusions
(including 1589), and reject daily eligible coverage less than the existing
historical source coverage minimum. The full market payload is processed in
RAM and not persisted, nor emitted in CI logs/artifacts. The only output
contains date/aggregate eligible bar counts, intersected stock cohort size,
11-trading-interval raw-price return distribution summary, and a SHA-256
fingerprint. No trade signal, position, trade simulation, database changes
or LINE messages.

A **separate synthetic** CI job exercises the same cross-sectional streaming
algorithm with 241 fabricated weekday sessions and 650 fabricated tickers.
It verifies 650 240-day exact-price SMAs and five full 12-feature technical/SMC
future-prefix calculations, using a bounded 241-bar per-symbol ring buffer.
Synthetic stock dates are **not** proof that those dates were actual TWSE
market sessions or that the archived 2022 OHLCV has been retrieved.

Known restrictions: the real source test fetches only twelve days and
therefore **cannot** claim a real 240-day MA or full market historical factors.
The 241-day stress is entirely synthetic; the CLI deliberately has no flag
to request that many TWSE HTTP calls. Historical constituents are survivors
from today's official registry, not a true point-in-time delisted roster.
Historic dividend/corporate-action adjustment, independently archived source
vintage, and pristine future holdout performance have not been verified.
Model release remains BLOCKED. Storage protections remain unchanged at
800MB/50MB, all Neon price/factor writes stay disabled and no paid capacity
is required.

Further expansion must separately validate HTTP capacity/latency and
exchange source quotas before attempting an entire 241-day real-market pass;
the 12-day canary does not establish permission or free quota for that.
