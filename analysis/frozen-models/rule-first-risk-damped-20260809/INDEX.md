# CURRENT CANONICAL FROZEN MODEL — Race Tantei

**Model:** `rule-first-risk-damped-20260809`  
**Status:** FROZEN / ANALYSIS-ONLY / NOT DEPLOYED  
**Rules:** 316 (every rule is bet-type-specific)  
**Backtest data end:** 2026-08-02  
**Historical venue-days:** 642  
**Selected races:** 3210 = exactly 5 races × 642 venue-days

## Structural fixes
- No bet-type-agnostic rules.
- Minimum 3 tickets per selected race; maximum 10.
- One ticket may receive at most 35% of the race budget.
- High-odds risk damping: target weight `min(1,(100/representative_odds)^1.5)` with 100-yen minimum per ticket and 35% cap.
- All six JRA bet types may be used; no fixed number of bet types per race.

## Completion gate
For **2,000 / 5,000 / 10,000 yen** courses, all of the following pass:
- overall ROI >= 200%
- all 3 time-period ROIs >= 200%
- all 5 season-balanced fold ROIs >= 200%
- overall / every period / every fold remains >= 200% after removing the 5 largest winning payouts in that group
- every bet type ROI >= 200%
- minimum 3 tickets per race
- single-ticket stake <= 35%
- full 642 venue-day coverage

## Backtest snapshot
- 2,000 yen: overall 343.39% / top-5 removed 297.47%
- 5,000 yen: overall 344.73% / top-5 removed 298.72%
- 10,000 yen: overall 345.34% / top-5 removed 300.08%
- Worst fold after top-5 removal across all courses: 205.93%
- Worst bet-type ROI across all courses: 263.86%

## Canonical storage
**ChatGPT Library is the single source of truth for the full model body:**  
`/RaceTantei/FrozenModels/rule-first-risk-damped-20260809/`

Pointer: `/RaceTantei/FrozenModels/CURRENT_CANONICAL_MODEL.json`

Files there include the exact `rules.json`, `policy.json`, `summary.json`, `manifest.json`, audit script and full reproducibility bundle.

**Bundle SHA256:** `89cb4057828f125b23161be843b13033e1e7e81cb934054dd74663f5a3cce0fd`  
**Rules JSON SHA256:** `6afa77ed6c648fe19512b0b68f99a48ac63d175f17eb74cec414a7c8c710c344`

This GitHub branch intentionally stores identity/policy/validation metadata only, to avoid competing copies of the canonical rule body.

## Holdout integrity note
2026-08-08 is **not** a pristine holdout for this revision because the failure of the deprecated 419-rule model motivated the structural redesign. Do not describe 8/8 as untouched OOS for this model.

## DO NOT USE
- deprecated 419-rule `rule-first-20260809-rebuild`
- any v16/177 recovery artifact
- 800-rule 50/50 model
