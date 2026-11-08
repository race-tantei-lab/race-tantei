# 2026-11-08: Independent two-stage six-market payout learner — REJECT

Experiment: [GitHub Actions #42447347718](https://github.com/race-tantei-lab/race-tantei/actions/runs/42447347718), conclusion **success** (the experiment succeeded; the strategy FAILED profitability).

## A genuinely new model rather than replaying old bets
- Independently enumerated 1,461,364 ticket candidates in all six markets; 37,442 were actually paid in the pinned public mirror.
- 7,094 races: 3,142 in 2024; 3,139 in 2025; 813 in Jan–Mar 2026.
- Stage 1 LightGBM binary paid-ticket event; Stage 2 separate LightGBM conditional payout size, with TRAIN-ONLY 97.5th-percentile per-market payout clipping.
- Financial estimate = paid-event probability × smearing-adjusted conditional cash amount. Winner classification accuracy and logloss were not targets.
- All 15 distinct pair types allowed; two different types / race; five selected races / eligible venue-day; ¥1,000 + ¥1,000 per race. No zero-ticket/one-race cherry picking.
- 384 monetary/risk/pair policies tested on 2025H1 ONLY; 291 meet the >=100 races and >=20% paid-race floor. Choose the 2025H1 highest largest-race-removed realized cash ROI. Refitted payout heads on 2024+2025, left selected policy unchanged through 2026.
- Selected H1 pair is the indexed pair 6 = ワイド + 馬単. (All 15 pairs considered, not a forced selection.)
- Past race-tantei selected bets and retroactive edits not used.

## Historical realized payout-based test
| Period | Races | Venue-days | Stake yen | Returned yen | Profit yen | ROI | Largest paid race removed (original stake) | Paid race % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2025 Jan–Jun rule selection | 720 | 144 | 1,440,000 | 1,476,100 | +36,100 | 102.50694% | 97.375% | 24.02778% |
| 2025 Jul–Dec unchanged rule | 720 | 144 | 1,440,000 | 1,031,100 | -408,900 | 71.60417% | 65.03472% | 23.33333% |
| 2026 Jan–Mar frozen policy | 360 | 72 | 720,000 | 402,600 | -317,400 | 55.91667% | 51.58333% | 23.05556% |

No incomplete eligible venue-days in these three periods. Report output contains month, market and stake details in the workflow artifact. Raw 2026 achieved neither original recovery rate >=400% nor trimmed 400%. **REJECT.**

## Data and production safety limitations
- Settlement data were sourced from pinned *third-party* JRA payout mirror, Kenseimk/keiba-agent commit `f552ca8628646f39b05ffdbdc3ab8734939ffd66`. Not independently reconciled with official JRA records.
- The model input included archived **final win odds**; they were NOT independently time-verified pre-T−15 official JRA combination quotes. The independent candidate forecast amounts are research estimates, not valid replacement official JRA odds.
- Prior experiments had already inspected 2026 results, so this is NOT a genuinely untouched prospective performance test.
- No Workers, D1, main or live tickets touched. No monitoring, recurring automation, or deployment introduced.
- This research file must **never be promoted to production** on the basis of these data. A profitable replacement model has NOT been established.
