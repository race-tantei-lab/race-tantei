# 2026-11-10 Outsider ranks 11–18 — all-six-market cash-first extraction

**Completed GitHub Actions**: https://github.com/race-tantei-lab/race-tantei/actions/runs/42737973429

- Research code: scripts/research-nov2026-outsider-sixmarket-cash-first.py
- Preserved ZIP artifact id 13727827637, name outsider-rank-11-18-six-market-roi200-cash-cells, expires 2026-12-10.
- Dataset: same 136 pinned monthly third-party cash-payout CSV (2015-2026 Apr), 30,545 races with ≥11 eligible runners. Training period 2015–2022: 21,937 races. Forward 2023 2,666; 2024 2,585; 2025 2,638; 2026 Jan–Apr 719.
- New independent cash universe: 56,992,647 nominal ¥100 bet tickets in 2015-22, including at least one horse at ranks 11–18 in **all six** bet markets. Distinct from the prior top-10 search. Strictly enumerated all 99 predetermined category conjunction schemas per market (all singletons/pairs of 13 outsider-centric features plus eight registered triples): 594 schema-market families.
- Cash-only direct historical mining; NO prediction model trained.

## Findings

| Market | Historical cash tickets | Gross ROI≥200%, n≥20 | Robust ROI≥200% after biggest race removed, n≥100 |
|---|---:|---:|---:|
| 単勝 | 104,567 | 16 | 1 |
| ワイド | 1,282,450 | 7 | 0 |
| 馬連 | 1,282,450 | 8 | 0 |
| 馬単 | 2,564,900 | 8 | 0 |
| 3連複 | 7,394,040 | 11 | 0 |
| 3連単 | 44,364,240 | 14 | 0 |
| **Total** | **56,992,647** | **64** | **1** |

The one historical-robust rule is WIN, categorical indices `outsiderOdds=4, drawMin=5, ageMax=3` (schema values represent buckets, not raw odds, draw or age):
- Train 2015-22: 439 tickets, stake ¥43,900, paid ¥105,170, gross ROI 239.5672%, max race payout ¥14,640, after exclusion ROI 206.2187%. Only 10 winning tickets.
- 2023: 58 tickets, stake ¥5,800, paid ¥12,510, gross ROI 215.6897%, after removing max race ROI **0.0%**.
- 2024: 68 tickets, paid ¥0, ROI **0%**.
- 2025: 62 tickets, paid ¥10,300, gross ROI 166.129%, max-race-removed **0%**.
- 2026 Jan–Apr: 19 tickets, paid ¥0, ROI **0%**.

**Conclusion: NO adoptable historical outsider condition, despite directly extracting every ROI200 cell in this enumerated universe.** Both prior top-10 search (878 schemas, 26,098 historical gross ROI200 cells / 974 max-race robust, only one repeats in 2023 and fails 2024) and new outsider search fail independent year-over-year ROI200 reproduction.

## Next research (no repeats)
- Search qualitatively new ex-ante variables not represented in odds-rank and race metadata: runner **past performances**, surface/distance, going, pace, workouts, jockey/trainer, T-15 odds/market interactions. Verify availability, licensing and timestamp; do not invent or infer 15-minute market snapshots from final odds.
- Explicitly define bounded combinatorial spaces and exhaustively extract actual-yen ROI200 cells BEFORE constructing a combined buy strategy.
- At every selection stage, track dates, stakes, payouts, max-race-removal, effective sample size and distinct market legs. No global all-possible claim. Require 5 races/venue/day and two different bet markets in eventual production model; stage-1 cash mining is individual ticket cells, not a finished 5R+2-market betting product.
- Do not change main, D1, Workers or production website. ROI200 not guaranteed.

Source official JRA reconciliation incomplete; final archived win odds not T-15 official.
