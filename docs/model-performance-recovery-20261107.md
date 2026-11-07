# Completed model: fix implementation drift, then validate real ROI

Date: 2026-11-07. Model SHA and race selection are unchanged.

## Verified root cause: production did not follow its own historical policy

The frozen model declares *top five raw predictedProbability × official JRA odds by bet type*, then **ln(probability) + 0.4 ln(odds)** reranking. Both deployed-path TypeScript and legacy Python live generators instead used **0.2** and scored *all* available combinations. That is a reproducible specification-versus-execution mismatch, not a statistical guess about profitability.

The present change aligns both generators with the declared historical candidate and score logic. The live same-day/30-day recency multipliers remain part of the final score **after** the raw EV top-five restriction. This is a fidelity repair, NOT an independently validated profit upgrade.

## Other causes that have NOT been cleared

- The public ten-year 431.6505898681471% was calculated on a full historical archive used for model development. It is neither strict out-of-sample ROI nor an unbiased estimate of future returns.
- Historical official-odds capture times have not been proven equivalent to the real T-15 lock.
- Real production profit is unknown until the read-only actual ROI audit successfully reconciles every selected race and both settled tickets; pre-deadline missing races must remain visible.
- Live win-probability model 56-feature, 500-tree weights and same-day/30-day correction have **not** been independently validated for this repaired candidate. Do not substitute a new model or relax validation.

## Acceptance for production performance claims

1. Reproduce the above contract tests in CI for *both* generators.
2. Require strict chronological retraining / prediction: for each evaluation race use only feature histories, model weights and selection thresholds determined before that race date; do not use the 431% full-archive training fit as out-of-sample evidence.
3. Apply **both** the fixed exactly-five-per-venue race selector and the same pre-T-15 official-odds snapshot to all candidate variants.
4. Evaluate 2 different ticket types, three stake-only courses, missing selections, returns, refunds, and payout verification against JRA, without survivorship exclusions.
5. Report total weighted ROI, per month, by race venue, by bet type, by odds bucket, and trim-largest-wins stress. Do not tune on the untouched final evaluation segment.
6. Promote a new model version only after independent forward/holdout evaluation and subsequent prospective results support positive ROI; no historical success or synthetic test can establish that on its own.
7. During rollout, check CI, *both* Workers deployment results, T-15 finalization integrity on actual race days, actual settled ROI and free D1 quota. Never edit prior locked predictions or backfill simulated bets as actual results.

## Why this patch does not assert ROI >100%

Restoring a contract that was itself fit and assessed in-sample cannot demonstrate profitability. The observed production drawdown remains a separate statistical and operational problem. Public presentation should distinguish retrospective in-sample 431% and actual live return.
