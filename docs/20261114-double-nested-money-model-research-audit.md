# 2026-11-14: double-nested predictive-method CASH discovery v9

**Actual result:** `NO_VALID_DOUBLE_ONLINE_ROI200_MODEL`, **0** model admissions, main and production unchanged.

## The algorithm

Instead of merely tuning a fixed betting filter or permanently choosing a favored model, both levels of the *prediction-method selection machinery itself* adapt by month and venue:

1. The lowest level constructs 765 single- and dual-market ¥2,000 cash actions from six bet types, under 672 different past-only ticket-generation methods.
2. The middle level runs **756 cash-meta-selection methods**. Each month, each venue independently chooses a base action generator using only already-settled earlier months. These methods differ in training horizon (3–96 months), venue pooling, profit-robustness objectives, sample shrinkage and cash support.
3. The outer level scans **1,728 method-of-methods**, each selecting among the 756 mid-level methods according to their own previous-month cash ROI and payouts, with a previous-cash-based stake multiplier. The choices are recomputed separately per venue/month, not frozen after one training period.

All per-venue-day race positions are selected before the outcome month is fed into the money model. For the **2017-01..2024-12** historical walk-forward selection period, the research procedure finds model admission candidates if and only if aggregate actual monetary ROI is at least **200%**, ROI excluding the largest returned single race while retaining the entire stake is at least **200%**, paid race hit rate is at least **20%**, and no venue/day has fewer than **3 different bought races**. A chronologically untouched **2025-01..2026-04** test is run only for development-qualified algorithms.

## Completed numerical execution

- [GitHub Actions run #43586184596](https://github.com/race-tantei-lab/race-tantei/actions/runs/43586184596): completed **successfully**, including self-tests for the strict cash model gate.
- **672 base money forecasters**, **756 intermediate cash-method selectors**, **1,728 outer dynamically re-trained method-of-methods** fully enumerated.
- `developmentQualified = 0`, `independentQualified = 0`, `models = []`.
- This is **not** evidence that no algorithm could ever meet the user's requirements. It establishes only that this finite, time-locked search family yielded no eligible model.

## Other independently executed search branches today

- [v6 two-expert adaptive multi-ticket portfolios](https://github.com/race-tantei-lab/race-tantei/actions/runs/43584384795): 12,960 method combinations, zero qualifying.
- [v7 spectrum of alternative payout-ranked tickets](https://github.com/race-tantei-lab/race-tantei/actions/runs/43584754216): 3,168 methods, zero qualifying.
- [v8 two-part direct horse-form cash machine learning](https://github.com/race-tantei-lab/race-tantei/actions/runs/43585172506): 32 pre-race/form features, 2022–24 pooled validation, zero qualifying.
- [Independent six-market historical cash-source integrity audit](https://github.com/race-tantei-lab/race-tantei/actions/runs/43585426317): no major 2026 payout coverage collapse detected, although independent official payout reconciliation remains undone.

Historical research payouts are third-party and ranking features use **final race win odds**, not independently validated official JRA quotes available at the target **T−15** time. Full 2026 Aug-Nov production holdout is not covered here and may not be fabricated from later information.

**Adopted production model = none. Deployment and historical settled tickets remain unchanged.**
