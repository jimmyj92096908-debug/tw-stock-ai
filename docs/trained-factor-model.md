# Trained Factor Research Model — verifiable deliverable

**Goal:** a real, reproducible statistical model that learns coefficients from the
existing Taiwan stock database; retains deterministic research ranking; and
refuses to issue trade instructions until a separate release acceptance.

This is not an LLM trained on stock prices and is not a licensed investment
adviser. The existing factor composite score remains the stable benchmark.

## Model I/O

- Dataset: daily_composite_scores, daily_prices, daily_adjusted_prices and
  (for latest ranking) stock_master.
- Features known on signal day t: overall score, technical score, SMC score,
  short/swing/long horizon scores, and factor coverage. Optional missing
  factor scores receive a neutral value **with an explicit missing indicator**;
  missing closing price and coverage below 0.5 are excluded.
- No chip feature can be claimed complete while stored chip scores remain absent.
  No future label enters the feature vector.
- Label: adjusted close at next actual raw-price trading session t+1 to
  adjusted close at t+6, five subsequent observed sessions. No filling
  missing adjusted prices from raw prices.
- Split fixed before training: development signal dates before 2026-10-01,
  holdout dates on/after 2026-10-01. Purge development cohorts whose t+6 exit
  reaches the holdout.
- Model: date-demeaned **ridge regression** with immutable penalty lambda=2.0
  and ±50% clipped training labels only; development dates equally weighted.
  No holdout labels in training and no hyperparameter search.
- Ranking: predict relative forward excess for eligible stocks, select top 20%
  for research metrics, compare against equal-weight eligible same-day
  benchmark and original composite-score ranking. A day is skipped *entirely*
  if an eligible ticker lacks a forward adjusted return.
- Research cost scenario: 30 basis points round trip (hypothetical, not a
  verified brokerage fee); publication approval is a separate gate.

## Reproduce

Provide a protected read-only DATABASE_URL for database twstock, then run:

    python scripts/trained_factor_pipeline.py train --start 2026-07-01 --holdout-start 2026-10-01 --end 2026-11-19 --model-out research-model.json --report-out research-evaluation.json

    python scripts/trained_factor_pipeline.py rank --model-in research-model.json --limit 10 --output research-ranking.json

The pipeline uses SET TRANSACTION READ ONLY. Model JSON contains coefficients,
feature schema, development fingerprint and training counts, never secrets.
The audit JSON has aggregate metrics. The ranking JSON has available code,
historical signal date, relative model ranking and **always** abstain=true
and live_trading_approved=false.

## Completion versus acceptance

| Gate | Meaning |
| --- | --- |
| Implemented | Training, inference, research evaluation, artifact and input guards committed |
| Offline tested | Independent CI passes all model tests (synthetic and mocked data only) |
| Real-data trained | Coefficients fitted on development-only Neon rows, with counts |
| Holdout assessed | Frozen coefficients evaluated on adjusted-price withheld labels |
| Investable | NOT claimed. Requires point-in-time revision audit, delistings, liquidity, costs, non-overlapping portfolio backtest and independent untouched future data |
| Published as trade signal | DISABLED until explicit operational approval and independent verification |

## Observed trained model result (read-only Neon, 2026-11-20)

- 57 development dates, 1,083 stock-date training observations.
- 21 withheld-date cohorts, 346 stock-date evaluation observations.
- Development mean net excess: +0.9303 percentage points per overlapping five-session cohort.
- Holdout mean net excess: **-2.1145 percentage points**; positive net excess on 28.57% of dates.
- Original composite-score holdout comparison: about -2.1350 percentage points.
- Saved fitted weights, sufficient statistics for independent coefficient re-solve, research ranking snapshot and full aggregate evaluation are in models/tw-factor-ridge-1-*.json.
- Latest research ranking snapshot dates from 2026-11-19 and contains 153 eligible stocks; it is not a real-time trade list.
- Holdout labels were excluded from coefficient fitting, but the Oct/Nov period had **already been examined for the earlier v2 model**. It is *not* a pristine independent holdout for model-design claims. A genuinely new future sample is still required.
- Acceptance decision: **research model implemented and numerically verified; investability rejected.** No trading signal can be published.

## Research limitations

Company actions can retroactively adjust historical prices. Historical composite
scores may have been recomputed after the original signal date: this is NOT
necessarily a reconstructible point-in-time dataset. Delisted, suspended and
unpriced instruments are underrepresented; the chosen 20% is relative to the
evaluable universe, not the entire Taiwanese equity market. Five-day rolling
forward labels overlap and are dependent.

Earlier fixed composite-model holdout showed negative research performance:
21 Oct–Nov adjusted cohorts had mean net excess around -2.135 percentage
points relative to the eligible-universe gross benchmark at hypothetical
30 bps round-trip cost. Keep this failed holdout visible; do not optimize
parameters on the same holdout to claim success.

No production Neon writes, registered LINE Webhook changes, existing
linewebhook Deployment 4 changes, private-message access or trading are
authorized by this research model.
