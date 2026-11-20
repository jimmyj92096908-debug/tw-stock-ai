# Factor model v2 — adjusted-price & holdout acceptance

## Model scope
This is a **rules-based research evaluator**, not a trained predictive AI or an executable brokerage strategy. It retains v1's fixed top-20% descending composite score, minimum 50% factor coverage, same-day source price, and signal-after-close assumption. Exclude stock 1808.

## Safer forward outcome
At signal session t close: rank without looking at future prices. Count trading sessions using the **raw verified daily_prices timeline**, never a sparse adjusted-price sequence. Require actual adjusted bars at t (signal), t+1 (hypothetical next-session close entry) and t+6 (five-session later close exit). Never backfill missing adjusted prices with raw prices. If a qualifying five-or-more-stock day's ANY candidate lacks a valid forward label, mark that entire cohort **incomplete** and exclude it from return estimates. This is conservative and explicitly records attrition; not a fix for survivorship bias.

## Predeclared date split and costs
- Fixed holdout start 2026-10-01; an evaluation date before that belongs to development.
- Exclude development cohorts with any holding-period exit date on/after 2026-10-01; no development label can cross into holdout.
- No parameter search or retuning against the October/November holdout. For illustration only, subtract a **30 bps round-trip cost** (0.30 percentage points) from the selected cohort's five-session gross return. This is not a verified trading-cost schedule and ignores market impact, liquidity, transaction tax variation and other fees.
- Show development and holdout separately; if a period has no complete cohorts, show null, never invent return observations.
- Because rolling 5-session cohorts overlap, neither their returns nor hit rates are independent. This report is NOT implementable portfolio CAGR, alpha, Sharpe, win probability or a causal model.

## Actual read-only Neon coverage check, 2026-11-20
2026-07-01–2026-11-19 had 2,780 scored records with >=0.50 coverage, 1,856 matching a non-null **same-date adjusted close**. Among dates with >=5 adjusted signal stocks: 96 dates had sufficient cohort size, only 84 dates had every prospective forward adjusted label, 57 completed development dates remained after holdout-boundary purging, and 21 complete holdout dates were available. The exact figures may change with future backfills. These counts do NOT imply favorable performance.

### Exploratory adjusted-price outcome from read-only Neon SQL
Predeclared holdout boundary: 2026-10-01; assumed round-trip cost: 30 bps.
- Development **57** complete cohorts: mean five-session selected gross **+1.2712%**; net **+0.9712%**; benchmark gross **-0.0332%**; mean net excess **+1.0044 percentage points**.
- Holdout **21** complete cohorts: selected gross **-3.1220%**; net **-3.4220%**; benchmark gross **-1.2870%**; mean net excess **-2.1350 percentage points**; positive net excess on only **28.57%** of dates.
- These are overlapping date cohorts, and neither an implemented portfolio nor independent samples. All figures are research snapshots from 2026-11-20 and may change after data backfill.

**Acceptance decision: FAIL for positive holdout evidence.** Do not promote to signals or optimize against this holdout. A later, truly unseen future interval must be used after any predeclared model redesign.

## Reproduce
Use an authorized read-only Neon PostgreSQL DSN:
```bash
python scripts/evaluate_factor_model_v2.py --start 2026-07-01 --end 2026-11-19 --holdout-start 2026-10-01 --round-trip-cost-bps 30 --output model-v2-evidence.json
```
The CLI invokes `SET TRANSACTION READ ONLY` and stores only aggregate cohort metrics and exclusion counts. Do not upload private credentials or private company records. Before production usage, independently audit corporate-action verification and adjusted-price reproducibility, delistings and stale bars; verify robustness using an entirely new time interval, and measure realistic execution cost and liquidity.

**This PR is not a live investment signal, model profit claim, or LINE deployment. The original LINE Webhook Deployment 4 is untouched.**
