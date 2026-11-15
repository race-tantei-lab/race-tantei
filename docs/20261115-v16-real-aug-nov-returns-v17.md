# 2026-11-15: Real August–November live-data replay of the NEW v16 cash methods

**Result: neither new v16 method reached 200% ROI after the historical archive ended on 2026-08-09.**

Successful read-only GitHub Actions job: https://github.com/race-tantei-lab/race-tantei/actions/runs/43695432459

## Comparable complete on-time venue-days, 2026-08-15 through 2026-11-14

The D1 selection states contain 30 race days, 370 selected races across 74 venue-days. Exactly 266 races had two different positive-stake Light tickets recorded, settled and locked at least 15 minutes before start; 87 selected races did not have an exact pair and 17 were missing/late at the 15-minute lock. This leaves **39 full venue-days, 195 original selected races**, when all five races of a venue-day had eligible records. All incomplete venue-days (35 of 74) were excluded **in their entirety**, not chosen based on realized return. The 96-month policy purchases three of the five complete candidates, leaving 117 evaluated races.

| Calculation on SAME 39 covered venue-days | Existing equal-stake model | New six-month profit-max model | New 96-month ROI-max model |
| --- | ---: | ---: | ---: |
| Purchased races | 195 | 195 | 117 |
| Stake yen | 390,000 | 390,000 | 234,000 |
| Real-money D1-based *scenario* return yen | 249,400 | 282,840 | 154,760 |
| Profit/loss yen | -140,600 | **-107,160** | -79,240 |
| ROI % | **63.94872** | **72.52308** | **66.13675** |
| ROI after largest single paid race removed % | 60.64103 | 66.56923 | 56.21368 |
| Paid-race hit % | 31.28205 | 31.28205 | 27.35043 |
| Target ROI >=200 both with and without largest paid race | No | **No** | **No** |

The six-month strategy decreases monetary loss by ¥33,440 relative to the equal-stake original on an identical 195-race denominator. It does not produce profit.

## Per-month ROI % on complete comparable venue-days

| Month | Venue-days | Original equal-stake | New 6-month | New 96-month |
| --- | ---: | ---: | ---: | ---: |
| 2026 Aug (first eligible selected live date Aug 15) | 5 | 86.00 | 129.52 | 109.53 |
| 2026 Sep | 5 | 36.60 | 23.96 | 18.93 |
| 2026 Oct | 22 | 54.77 | 55.39 | 41.00 |
| 2026 Nov through Nov 14 | 7 | 96.57 | 120.34 | 147.86 |

Cash arithmetic was cross-checked by independently summing every month's stakes, paid amounts, race counts and venue-day counts back to the quoted overall percentages.

## Critical interpretation

- The new cash rules were developed from retrospective 2017-Jan–2026-Aug09 original frozen tickets. **602.29% and 788.74% historical are not evidence of forward live profit.**
- This replay used production-selected two-ticket combinations from an ORIGINAL horse selector trained through 2026-08-09. Only the new CASH prediction/training horizon, race selection (5 or 3) and stake allocation were replayed. This does **not** evaluate a wholly new horse model.
- The replay applies 2,000 yen per purchased race, 1,800/200 split by expected return, to the actually recorded real-money settlements normalized to yen per 1,000; the newly allocated hypothetical stakes were **not placed live**. The original actual Light stake is ¥2,000 per race on the eligible sample.
- Every included ticket had a locked-at timestamp at least 15 min before race start; **the assumed odds values are not independently proven official JRA T−15 quotes**.
- This does **not** compute the actual total-site ROI for all 370 frozen selections. Incomplete/late/missing data prevent that; excluding 35/74 venue-days creates sample bias. In particular no claim of 200%-eligible prospective production model is permitted.
- Returns are based on recorded D1 settlements and have not been externally cross-reconciled to the JRA website.
- The production and GitHub main branches, existing bets and results remain unchanged.

This audit answers the user's question about what happened **after August began**, not merely the earlier historical 2017–Aug09 backtest.
