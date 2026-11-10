# 2026-11-11 pre-race form condition integrity gate (not an ROI result)

Source inspected: `scripts/research-nov2026-chronological-form-money-conditions.py` blob `69b9c7896c9fcf3aa7d88c632e7643a4300b31d5`.

## Concrete blockers observed
1. `form_categories` initializes every one of 20 form category arrays as `np.zeros(336*n,dtype=np.uint8)`; missing race matches and missing horse numbers skip without invalidating their ticket rows. Zero is a legitimate bucket, so these rows can enter false profitable cells.
2. The main program uses `join_pre_result_races_by_horse_identity` from the 56-feature module. Its join must be replaced with a date-aware unique race identifier and explicit horse identity verification before use.
3. Existing code explicitly mines 2024–2025H1, selects on 2025H2, and evaluates 2026, not the mandated 2015–2022 / 2023–24 / 2025–26 split.
4. The source disclaims official historical T-15 odds. The third-party payout mirror remains unverified against JRA official settlement.

## Required fail-closed design for a NEW finite search
- Verify raw source columns, provenance, and event-time availability for each historical feature. Do not treat final odds as T-15.
- Build a unique `(race_date, venue, race_number, horse_number, horse_identity)` join; reject duplicates, ambiguous matches and future-dated feature rows.
- Initialize category arrays with an invalid sentinel (e.g. 255), and retain an independent boolean `valid_ticket` mask. Reject all invalid rows BEFORE any cash accumulation or threshold search; never infer validity from category value.
- Report coverage and excluded race/ticket counts separately for each year 2015–2026. Fail the run if historical coverage cannot support the fixed periods.
- Pre-register finite conditions and candidate ticket universe before accessing 2023+ outcomes; discover on 2015–2022, freeze, check 2023 and 2024 separately, show 2025/26 only as contaminated reference.
- For each cell report number of bets, distinct races, purchase JPY, payout JPY, raw ROI, and leave-largest-payout-race-out ROI, with year breakdown and overlaps. No production promotion without JRA official payout reconciliation and actual T-15 feature feasibility.
- Do not repeat already completed 878, 594, 240, or 180 schema runs.

## Run status
This document is a code audit and proposed validation gate, **not** a new executed payout search. No GitHub Actions run or artifact is claimed. No ROI200 cell was found or validated. Production main, D1, Workers, and website remain untouched.
