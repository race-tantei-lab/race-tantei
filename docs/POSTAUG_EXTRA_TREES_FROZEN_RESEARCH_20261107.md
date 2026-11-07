# Post-2026-Aug independent model candidate: frozen research policy (2026-11-07)

## What was actually constructed

An **independently fitted ExtraTreesClassifier**, 120 randomized trees with
`max_depth=14`, `min_samples_leaf=35`, `max_features=0.7`, and
`random_state=20261107`. 56 historical/pre-result features,
trained strictly through **2026-08-09**, without 2026-08-10..11-07 results.
Model weights are reproducibly serialized as a joblib artifact in
the PR research workflow, SHA-256 and exact prediction reload parity checked.

**Not deployed; not a confirmed real-money production result.** This new model
is not the existing LightGBM runtime. The research uses D1 JRA stored
payouts, not historic after-race odds. Its race selections and tickets are
hypothetical counterfactual decisions reconstructed with date-safe features.
Exact pre-T15 capture/replay and all JRA external payout evidence are not yet
independently proven; past data has already been examined by previous research.

## Frozen prospective comparison *candidate*, selected with hindsight

- Pre-result race score: sum of **three largest ExtraTrees predicted win
  probabilities**, no odds and no post-result inputs.
- Select **3 races per venue and day** before events. Never select by result.
- Exactly two different tickets per selected race:
  - ワイド: predicted 1st and 2nd horse, stake **¥200**.
  - 馬連: predicted 1st and 3rd horse, stake **¥1,800**.
- ¥2,000 planned per race; only canonical JRA actual payout table to settle.
- Ranked horse numbers and types MUST be frozen before first relevant race
  and no later than T−15, independently of public prediction choices.

## Historical counterfactual paired results

| Observed period | Paid candidate races | Hit races | Hit-race % | Stake | Actual JRA payouts in D1 | ROI % |
|---|---:|---:|---:|---:|---:|---:|
| Aug–Sep 2026 | 105 | 38 | 36.19 | ¥210,000 | ¥239,580 | 114.09 |
| Oct 2026 | 72 | 33 | 45.83 | ¥144,000 | ¥158,000 | 109.72 |
| Nov 1,7 2026 | 15 | 8 | 53.33 | ¥30,000 | ¥48,200 | 160.67 |
| Total | 192 | 79 | 41.15 | ¥384,000 | ¥445,780 | 116.09 |

The largest winning race payout excluded **with stake retained** makes
aggregate ROI **94.99%**, so profitability is fragile.
All 64 complete venue-days from a potential 68 were included; four venue-days
with incomplete result or six-market payout evidence were excluded and are
separately counted. This is not complete calendar ROI. There is **no truthful
claim** that the candidate was the pre-declared winner in the original
Aug–Nov period, because **12,375 candidates** were screened retrospectively
and these dates were already exposed. High ROI might reflect luck/selection
bias. Model did not use historical final odds or synthetic odds to rank horses.

## Required before any real-money live promotion

- Capture the newly frozen ExtraTrees ticket choice before T−15 with exact
  official pre-event feature provenance, no future labels, same selected venue
  days, all eligible races, including missing and late selections.
- Independently reconcile each winner and payout with JRA official results.
- Always compare **hit-race % AND actually settled ROI together** on identical
  locked populations, stakes and dates. Report largest-payout-removed ROI,
  complete venue-day coverage and failure counts.
- Establish out-of-sample prospective improvement over actual canonical picks,
  in multiple racing periods, robust to single jackpot wins.
- Independently prove model inference parity and successful Primary/Backup
  live safety before deployment; never overwrite old public bets, D1 history,
  or use JRA synthetic odds. Protect Cloudflare free-tier limits.

**Promotion to main/live: NO.** This is a fitted and frozen research candidate,
not a claimed profitable production-ready system.
