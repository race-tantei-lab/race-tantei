# 2026-11-11 odds temporal provenance gate (code audit, not payout result)

Inspected `scripts/research-nov2026-chronological-form-money-conditions.py` blob `69b9c7896c9fcf3aa7d88c632e7643a4300b31d5` on `research/nov2026-outsider-surface-distance-going-cash`.

## Additional concrete blocker

`form_categories` derives `rankFormMismatch` using `before_market=np.asarray([x[1] for x in r['horses'][:7]])`, then normalizes inverse odds to `market_score`. The module header expressly states that historical final WIN quotes do not establish official JRA T-15 quotes. Therefore the code does not establish that `rankFormMismatch` is available at the T-15 decision point. Any ROI cell involving it must be marked **not production eligible** until a timestamped official T-15 quote is verified for each historical race. This also applies to cash-context `oddGeom` and any feature using the same final quotes.

## Pre-registered integrity test for subsequent new cash search

1. Require `odds_source`, `odds_observed_at`, `race_start_at`, and official-source verification before enabling odds-dependent cells; enforce `odds_observed_at <= race_start_at - 15 minutes` and prohibit retrospectively final odds.
2. Separately track odds-independent form conditions and odds-dependent conditions, with no mixing in a production-eligible result table.
3. Validate unique `(race_date, venue, race_number, horse_number, horse_identity)` joins, invalidate unmatched tickets rather than zero-fill, and report annual exclusion counts.
4. Mine only on 2015–2022 outcomes, freeze candidate cells before checking 2023 and 2024 separately, and label 2025–26 contaminated reference.
5. For every retained cell output tickets, distinct races, stakes JPY, payout JPY, ROI, leave-largest-payout-race-out ROI, annual breakdown, and overlap with previously searched cells.
6. Third-party payout mirrors require independent official JRA payout reconciliation before adoption.

## Execution status

No GitHub Actions dispatch is available in the connected GitHub operations; this note is **not** a completed real-data cash scan, does not establish ROI200, and is not an artifact. Existing successful scans were not rerun. No production branch, D1, Workers, or website change.
