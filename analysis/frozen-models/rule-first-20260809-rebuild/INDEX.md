# Frozen model: rule-first-20260809-rebuild

Status: **FROZEN / ANALYSIS ONLY / NOT DEPLOYED**

This model was frozen **before inspecting the 2026-08-08 holdout**. Do not tune rules or policy from the 2026-08-08 result.

## Canonical identity
- Strict deduplicated rules: **419**
- Fixed DB: **7,695 races / 642 venue-days**, 2024-05-04 through 2026-08-02
- Historical selection: **exactly 5 races per venue-day = 3,210 races**
- Bet types: no fixed count; all six JRA bet types allowed
- Course budgets per selected race: **2,000 / 5,000 / 10,000 yen**, 100-yen units
- Rule gate: support >=24; each of 3 periods >=8; overall ROI >=200%; every period ROI >=200%; every period remains >=100% after removing its single largest payout
- Rule conditions contain no target date and no current-race outcome feature

## Frozen policy
- Ticket score = strongest matching rule durability score
- Keep tickets at least **99% of race-best score**, cap 10
- Race score = race-best ticket score / candidate-count^0.30
- Pick exactly top 5 eligible races per venue-day
- Split the full course budget over selected tickets in 100-yen units, as evenly as possible; remainder to higher-score tickets

## Robustness snapshot
- Light 2,000: **441.58%** overall; max-one removed **398.60%**
- Standard 5,000: **442.28%** overall; max-one removed **399.30%**
- Premium 10,000: **442.11%** overall; max-one removed **399.13%**
- Every one of the 3 time periods is >200% for all courses
- Every one of the 5 season-balanced folds is >200% for all courses

## Canonical persistent files
The exact rules and reproducibility bundle are stored in the user's persistent ChatGPT Library under:
`/RaceTantei/FrozenModels/`

Files:
- `rule-first-20260809-rebuild-rules.json` — the **actual 419 rules**
- `rule-first-20260809-rebuild-policy.json` — frozen live-selection policy
- `rule-first-20260809-rebuild-summary.json` — exact validation figures
- `rule-first-20260809-rebuild-manifest.json` — SHA256/input identity
- `rule-first-20260809-rebuild.tar.gz` — full reproducibility bundle including the 419 rules and five source scripts

Canonical bundle SHA256: `8ba42c8a3d4c01825d8c7a9180aa5b30bc0084c0470b3d9722b9db1efdbe5288`
Rules JSON SHA256: `ad81f4be88064e9b08756bd585019b487b8f96b3f4fc262710d02d8d149143c1`

The production/site path must remain unchanged until holdout evaluation is reported separately.
