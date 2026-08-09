# Race Tantei — Frozen rule-first model (2026-08-09)

This directory is a **non-production frozen model artifact**. Do not wire it into the site or production prediction path yet.

## Identity
- Model: `rule-first-20260809-rebuild`
- Strict deduplicated rules: **419**
- Fixed training/audit DB: 2024-05-04 through 2026-08-02, 7,695 races / 642 venue-days
- 2026-08-08 is **not** part of the fixed DB and had not been inspected when this freeze was created.

## Method
The fixed DB is mined first for uniform, reusable rules. Current-race results are never used as buy conditions. Historical results are used only to discover/audit rules. Horse/jockey/trainer history features are calculated using information available before each race and updated only after that race's features are frozen.

Strict rule gate: support >=24, each of 3 time periods >=8 samples, overall ROI >=200%, all 3 period ROIs >=200%, and each period remains >=100% after removing its single largest payout.

## Live selection policy
1. Ticket score = maximum durability score among matching frozen rules.
2. Per race, keep tickets whose score is at least 99% of race-best; primary cap 10 tickets.
3. Race score = race-best ticket score / candidate-count^0.30.
4. Pick exactly top 5 eligible races per venue-day.
5. No fixed bet-type count. All six bet types are allowed.
6. Course budgets: 2,000 / 5,000 / 10,000 yen per selected race. Allocate in 100-yen units as evenly as possible; remainder goes to higher-scored tickets.
7. For a truly unseen venue-day with fewer than five primary races, use only the same frozen 419 rules and the predeclared fallback ladder in `freeze_policy_v2.json`. Never add/tune a rule using the target-day outcome.

## Backtest / robustness snapshot
Light 2,000: full 441.58%; max-one-payout-removed 398.60%; periods 480.82 / 395.15 / 451.08%; 5-fold 439.41 / 327.83 / 374.40 / 496.88 / 576.14%.
Standard 5,000: full 442.28%. Premium 10,000: full 442.11%.

See `final_model_summary_v2.json` for exact values and SHA256s.
