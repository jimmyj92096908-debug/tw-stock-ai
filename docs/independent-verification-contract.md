# Independent Verification Contract — research-only (2026-11-24)

## Purpose and immutable release boundary

This document records acceptance criteria intended to be controlled by the owner/reviewer, **not by the code-producing agent**. Merging this document alone does NOT make it immutable: GitHub repository administration must separately enable a main-branch protection rule or ruleset requiring an independent reviewer and the **Independent Research Verification (Offline)** check. Require CODEOWNER review on changes to this document, the associated workflow, test cases and any eventual release threshold. A workflow in a PR cannot guarantee that its own rules cannot be weakened; the protected default branch and independent review authority must enforce that. Do not claim that enforcement is active until the admin confirms it with evidence.

## Explicit acceptance tiers

| Tier | Required evidence | Current interpretation |
| --- | --- | --- |
| OFFLINE_CODE_PASS | Run actual CLI in a process, verify expected research JSON twice; independent arithmetic oracle, generated properties, tamper / missing-input guards, existing model artifact parity, temporal leakage tests | Can pass while research release remains blocked |
| ISOLATED_DB_PASS | Disposable local PostgreSQL E2E of source ingest, derived factors and report, comparing primary keys and before/after counts | Not supplied by this offline workflow |
| VERIFIED_SOURCE_PASS | Official source provenance for all intended stock/date rows, adjustments and point-in-time issuer universe, no fabricated dates | Not supplied by this offline workflow |
| PROSPECTIVE_RESEARCH_PASS | Newly unseen, forward-frozen holdout, realistic cost and execution assumptions, risk controls, survivorship and corporate actions | Not met by existing 2026-11-20 fitted artifact |
| LIVE_RELEASE_PASS | Independent owner approval, production safety review and separately authorized delivery controls | **BLOCKED**; never unlocked by code CI |

### Three verification strategies

1. **Actual end-to-end execution**: `tests/test_independent_verification_e2e.py` runs `scripts/investment_model_pipeline.py` as a subprocess twice with production credentials removed and checks its real JSON artifact. This is an **offline E2E**; it does not claim to access or alter Neon or LINE.
2. **Generated property checks**: `tests/test_independent_verification_properties.py` uses deterministic, seeded integer-factor input generation (including missing factors) and checks coverage, bounds, monotonicity, missing-vs-zero distinctions and unknown-factor invariance. This is bounded generated-input coverage, **not** exhaustive fuzzing or Hypothesis shrinking.
3. **Differential oracle checks**: the same test file uses separately hard-coded reviewer weights and exact rational arithmetic (`fractions.Fraction`) to compare both score pipelines over hundreds of cases; a one-cent tie tolerance accounts for binary floating point.

Each new test suite is executed **twice** in the dedicated GitHub Actions job, so a basic flaky test is more likely to be seen. Two passes do not establish non-flakiness; monitor intermittent failures on multiple runs and investigate, never suppress them by blind retries.

### Non-negotiable invariants

- Current official TWSE/TPEx listed stocks only, exclude delisted stocks and 1589 in owner-requested current-universe research; do not describe this survivor-only population as a bias-free historical universe.
- Never fabricate missing prices or collapse missing factors into score 0. Repeated history imports must not overwrite existing primary keys.
- A feature available only after an as-of date cannot influence a score or historical decision from before that date.
- Research result dates, prices, chip dates and composite dates remain independently reported; yesterday's score cannot be relabeled as today's.
- A failed, non-pristine or missing holdout **must** preserve `abstain_from_trading=true`, `publish_line_trade_signal=false`, `orders_enabled=false`.
- Maintain no additional paid services, no production Neon writes, no index/table deletion, no LINE Webhook or messages during offline acceptance. Neon free-capacity and quota gates stay unchanged.
- **PASS is scoped**: a successful GitHub Actions job proves only its explicitly tested tier, not new official data, five-year coverage, total-return label completeness, positive alpha or release readiness.

## Reviewer workflow

1. Inspect the PR diff and compare it with the main-branch protected rubric. A change to the test/workflow/rubric must be independently approved; the author of implementation changes must not be sole approver.
2. Verify the exact commit SHA; require both existing Python Tests and Independent Research Verification (Offline) checks on that SHA, including repeat-run results.
3. Check failures are fixed at source. A test that intermittently fails or a new exception that is merely skipped is not PASS.
4. Inspect data/backfill/release controls separately. Keep `model_release=BLOCKED` while source completeness, corporate actions, historical PIT universe or clean future holdout remain unresolved.
5. If reviewer/ruleset enforcement is unavailable, record **GOVERNANCE_BLOCKED** rather than claiming Anthropic-style separation of inspection rules from the code-producing agent.

## Safe reproduction

```bash
python -m pip install -r requirements.txt
PYTHONPATH=src python -m unittest -v \
  tests.test_independent_verification_properties \
  tests.test_independent_verification_e2e \
  tests.test_fitted_artifact_consistency \
  tests.test_trained_factor_model \
  tests.test_investment_model_bundle
```

No `DATABASE_URL`, LINE token or other production secret is needed. This work does not authorize production replay, five-year writes, model promotion, LINE changes or trading.
