# Three-to-five races / two-distinct-ticket HIGH-HIT research (2026-11-07)

**Status: EXPERIMENT ONLY. High-hit hypothesis found, ROI 400% not proven, NO deployment authorized.**

Reproducible successful Actions: https://github.com/race-tantei-lab/race-tantei/actions/runs/42376187270

## Fixed operating constraints
- Exactly **3, 4, or 5 selected races per venue/day; 5 is the default**, and **never fewer than 3**.
- Exactly **two tickets with DISTINCT bet types per race**, drawn from existing JRA official-supported betting types.
- Optimize breadth and repeatability of *at least one ticket hit in each race*, rather than rare isolated jackpots.
- Public tickets must still be locked before T−15, must not be backfilled or revised, and all settlement must use JRA actual payout. Same-day results cannot affect prior race decisions.
- The user also retains a 400% ROI aspiration: no hit-rate result is a substitute for stable actual profitable ROI.

## Research design
- Retain the 56-feature LightGBM family, refit strictly before each evaluation year 2024, 2025, 2026 with chronology-safe runner states. No leakage from same-day finishes to features.
- Evaluate 5 winner/market blends (model-only, archived FINAL market-only, 30/50/70%-model probability), 10 fixed pairs of two distinct ticket types (win+wide, win+quinella, wide+quinella, wide+trio, wide+exacta etc.), 5 pre-result race-ranking rules, and three fixed race counts (3,4,5): **750** predefined rule combinations.
- For every venue/day with enough valid research races, pick exactly k races by confidence score, not by their outcomes; exactly two individual ticket types per race. Compare per-race hit, per-ticket hit, and all-k races hit.
- Discover shortlist using **2024 only**; apply unchanged 2024 five-race leading policy to 2025/2026. 2026 archived results were already opened in previous investigations; never call them untouched final holdout.
- Official win odds here are historical FINAL odds, NOT saved official T−15 odds. **Payout ROI cannot be computed** because the historical wide/quinella/etc T−15 paid-ticket portfolio is unavailable.

## Highest 2024 five-race policy, frozen across years
Rank runners from 50% model + 50% archived final-market implied win probability. Select five races per venue/day by the sum of top-two horse probabilities. In every race, hypothetically buy:
1. One `単勝` ticket on predicted rank #1 horse
2. One `ワイド` ticket on predicted ranks #1 and #2 horses.

| Period | Full 5-race venue days | Races | At-least-one-ticket-hit races | Hit-race percentage | All 5 races hit venue days |
|---|---:|---:|---:|---:|---:|
| 2024 (research discovery) | 183 | 915 | 524 | 57.27% | 12 (6.56%) |
| 2025 (unchanged transfer) | 286 | 1430 | 835 | 58.39% | 16 (5.59%) |
| 2026 through Aug 9 (already inspected) | 173 | 865 | 500 | 57.80% | 11 (6.36%) |

The exact same horse/ticket/ranking strategy with **only three races per venue/day** has race hit 59.38% (326/549) in 2024, 61.31% (526/858) in 2025 and 60.69% (315/519) in 2026 through Aug 9. Entire 3/3 venues hit 43/183, 68/286, 38/173 respectively.

A similar, **third-ranked on 2024** market-heavy 30%-model/70%-market alternative (`WIN1_WIDE12`, top2 mass) yielded five-race hit percentages 56.94/59.23/59.19% in 2024/2025/2026, and three-race hit percentages 58.65/62.82/63.78%. This is **descriptive only**: selecting it after examining later years would introduce post-hoc optimization.

## Baseline actually locked 2026 Aug-Nov
Independent audit of actual T−15 Light-course two-ticket live bets (same complete date+venue cohort):
- 5R: 47/165 race hits = **28.48%**, **0/33** all-five-hit venue days, 58.09% ROI.
- 3R: 30/99 race hits = **30.30%**, **1/33** all-three-hit venue days, 64.44% ROI.
- Archived 2024–Aug 9 2026 discovery is **not** an apples-to-apples uplift over Aug–Nov 2026 live results: different period, market data times, scoring and cohort completeness.

## Critical limits
- The 2024 market-odds research archive is incomplete (1,228 races were dropped due to missing historical final win odds and 107 due to fewer than eight runners); 2025 drops 24 plus 105, and 2026 drops 80 plus 41. The candidate groups therefore cannot certify a complete real-world operating calendar.
- The odds are FINAL/after-race, NOT verifiably available at T−15; market-blended pre-race decision prices may differ.
- Wide and other two-type payoffs were not modeled here. **High hit rate can still lose money**, and no 400% claim is warranted.
- On the research sample only **~6% of five-race venue days** hit all five races, which falls very far short of “all races almost always hit”.
- If promoted at all, this approach must first be frozen on real official pre-T−15 odds with immutable two-ticket shadow results and actual JRA payoffs for the same future dates, with full payout coverage and no lookahead or D1 quota risks.

**Production changed:** No. **Profitability demonstrated:** No. **Next honest step:** prospective shadow with official T−15 quotes and immutable settlement, preserving free quota and existing public tickets.
