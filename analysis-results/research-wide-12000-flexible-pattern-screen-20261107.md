# Flexible race count + abstention research: 12,000 chronological OOF screens (2026-11-07)

## Verdict: NO 400%-ROI strategy; **not eligible for production**

Full successful GitHub Actions run:
https://github.com/race-tantei-lab/race-tantei/actions/runs/42369388625
Workflow job `flexible-patterns`: completed **success** and published the complete research JSON artifact. This means the computation finished; it does **not** establish betting profit.

### Method and search-space inventory
- The completed **56-feature LightGBM family**, rebuilt from prior-year historical results separately to score each year, with same-date feature-state updates only after all daily features are scored. Race outcome, popularity and final win odds are NOT model inputs.
- 2016–2023 runner history for first-year training, then strictly pre-2025 runner history to evaluate 2025, and strictly pre-2026 runner history to evaluate 2026.
- Candidate screen: 10 horse-ranking/price models × 6 odds bands × 4 minimum model-predicted EV floors × 5 race conditions × 2 race priority methods × **1,2,3,4,5 maximum races per venue day**, with **automatic abstention** when none qualifies = **12,000 pre-specified candidate rule configurations**.
- Rank only pre-result data (model predictions + *archived final* JRA win odds), then select at most K races per venue day; never use their finish results to choose a horse or race.
- Separate policy discovery and transfer: from 2024 archive odds results, require >=80 ticket bets and >=16 race dates, rank by observed ROI after deleting largest payout (keeping stake), freeze the highest 100 (5,702 pass sample-size screen) **before 2025 analysis**.
- 2025 measures these 100 previously frozen configurations, and 2026 measures the **same unchanged 100**, without tuning them against either year. 2026 has already been opened in earlier research and cannot be called a pristine final holdout.
- Outcome used for this specific screen: *single win-type ticket*, 100 yen theoretical stake, archived post-race/final odds. This is a directional hypothesis screen, not the actual site two-distinct-ticket strategy, not verified as official odds available at T−15, not an actual payout-table reconciliation.

### Results
- 12,000 rule configurations enumerated, 5,702 with sufficient 2024 dates and ticket count, highest 100 frozen on 2024 only, 100 transferred to 2025 (with minimum coverage).
- **Zero** shortlisted configurations reached 400% ROI after excluding the single biggest payout **in each of 2024, 2025 and 2026**, while retaining >=80 actual candidate bets and >=16 racing dates per year.
- Example of strongest 2024 trimmed candidate (single-win only, **NOT deployable**): model-predicted rank #2, odds 5–50, field under 12, bet at most one race per venue day. 2024 132 bets, hypothetical ROI 174.62%, 2025 196 bets, 106.17%, 2026 115 bets, 132.78%. 2024/25/26 post-largest-payout ROIs: 163.03%, 98.57%, 117.04%. Not close to 400%; 2025 notably fails even 100% after largest payout removal.
- Example best 2025 hindsight candidate (already frozen in 2024 pool): 2024 159.41%, 2025 168.56%, 2026 117.68%. Selecting this after viewing 2025 is policy selection on the validation year; not a clean 2026 independent promotion test.
- The same repo already has 2024–2026 official-odds two-type nested OOF and 2026 Aug–Nov real locked Light bets proving failures of other model/odds/selection families, with frequent catastrophic transfer.

### Why this is not proof that 400% is mathematically impossible
- Only 12,000 bounded, pre-specified hypotheses; infinite possibilities cannot be exhausted.
- Source is archived final single-win odds, not the complete six-type official JRA T−15 quote book. The exact all-market two-ticket counterfactual dataset is unavailable for these historical years, and missing context remains in this retrospective feature reconstruction.
- 2026 was already inspected; reoptimizing on any combination of 2024/25/26 would invalidate claiming a completely new untouched holdout.
- The pre-result feature reconstruction is a proxy for live Worker, not exact byte-for-byte feature/probability parity. Neither the numerical value of the selected pool nor its ROI is an actual paid-bet result.
- A substantial 400%-ROI claim requires future **immutable T−15 official-odds two-type ticket portfolios** settled against actual JRA payouts, without missing/late races or result-aware filtering, and multiple independent racing months.

### Action
No candidate passed. Do not alter `main`, D1, the Worker prediction/odds logic, or historical predictions. Do not misstate this exploratory run as "400% achieved", "new production model", or "no mathematical 400% possibility".

**Production promotion permitted:** NO.
