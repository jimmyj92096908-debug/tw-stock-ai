# Composite Factor Model v1 — research acceptance contract

This is a **rule-based, auditable factor ranking model**, not a trained LLM or machine-learning price predictor. It uses existing `daily_composite_scores.total_score` with a fixed, precommitted rule. The model's production data has not been independently validated as profitable.

## Inputs and ranking

At the close of date `t`, require a stored, non-null total score (0..100), `coverage_weight >= 0.50`, and an actual historical closing quote for the **same** `market, stock_id, t` tuple. Rank by score descending, coverage descending, and a deterministic market/code tie-break. Select the top 20% of each date's *evaluable* universe. A date requires at least five stocks to be evaluable.

## Backward-looking information and forward label

The score is determined using historical data already associated with `t`; the evaluation query does not calculate the score from future prices. It uses **session t+1 close as hypothetical entry** and **session t+6 close as exit**, a forward five-trading-session result. This choice avoids the unrealistic assumption that one can observe the full `t` close and simultaneously fill at it.

All benchmarks use the same date's evaluable stocks. Missing future closes are excluded from any measured cohort, *never* treated as zero or as a winning trade. Such exclusions create survivorship/selection risk; `exclusions` must be reviewed. Dates with no evaluable group return **null** metrics, not made-up performance.

## Measures

Reports a daily-cohort mean 5-session return, matching universe mean, mean excess return, positive excess fraction and top selected positive-return fraction. **Do not describe those numbers as strategy CAGR, risk-adjusted returns, implementable fills, or causal predictive skill.** Overlapping labels create serial dependence; do not apply ordinary IID significance claims.

## Execution

Install `requirements.txt` and run:
```sh
python scripts/evaluate_factor_model.py --start 2026-07-01 --end 2026-11-19 --output factor-evaluation.json
```
To produce the latest available same-day scored-stock ranking from the existing
score table, use `python scripts/run_factor_model.py --limit 10 --output
factor-ranking.json`. Its result includes actual score date, coverage,
signal close, ordered stock codes and an explicit research-only flag. This is
**not** an order request, broker connector or purchase recommendation.

A first **read-only exploratory SQL check** on November 20 found 2,753
same-date score/close pairs for July 1–November 19, 2026, with 2,490
evaluable forward return labels. Ninety signal-date cohorts (average 27.67
stocks per cohort) had at least five evaluable stocks. They showed mean
five-session top-cohort return +0.115%, same-day equal-weight eligible
universe -0.542%, mean difference +0.656 percentage points and
positive excess on 53.3% of dates. The 90 overlapping cohorts are NOT
independent, and these descriptive numbers are NOT verified trading
performance. No risk, dividend/split adjustment, cost or bootstrap confidence
interval has been applied. The result can change after official history
backfills or corporate-action data corrections.

Provide a protected `DATABASE_URL` for an explicitly least-privilege **read-only** database role. The script sets a read-only PostgreSQL transaction before its SELECT, makes no schema changes and transmits no LINE messages. Use an isolated snapshot or a read-only production role only when authorized. Evidence JSON contains aggregate metrics, dates and counts, no tokens or personal information.

## Gate for trustworthy production usage

1. Unit/SQL contract tests green and a real read-only SQL evaluation with date coverage and missing-forward counts recorded.
2. Independently review sample definition, date overlap, adjusted-vs-unadjusted closes and delisted-stock bias. At present the evaluator uses `daily_prices` **unadjusted** closes, so dividends and splits can distort returns.
3. Precommit any parameter changes before measuring a separate holdout period.
4. Verify more history, transaction cost model, fill assumptions, liquidity constraints, and regime robustness before making any financial claim.
5. LINE and production webhook are outside this model work; keep original Deployment 4 unchanged.

Current status: **implemented, regression tests pending CI and real-data research evaluation pending**. Not approved for live trading or investment recommendations.
