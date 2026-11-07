# OOF horse-level win-ticket exploration — 2026-11-07

**Decision: REJECT. No model or ticket policy that demonstrates sustainable 400% ROI was identified.**

Actions verified: https://github.com/race-tantei-lab/race-tantei/actions/runs/42366191243

## Purpose
Before spending scarce pre-T15 full-market data collection effort on new two-type shadow ticket variants, perform transparent forward-by-year research on original 56-feature LightGBM family to see if model/market odds discrepancy yields any stable *single-win* signal. This is an exploratory **approximation, not actual JRA T-15, not two-ticket ROI**.

Protocol:
- Chronological state construction with no future finishing positions in race-level features, and all same-day history updated after racing.
- 2024 validation: fit using only data before 2024; 2025 validation: fit using only data before 2025; 2026 diagnostic: fit using only data before 2026. Dates were previously observed in other analysis; this 2026 comparison does **not** establish a new untouched holdout.
- Archived final win odds used only in post-fit bet candidate scoring. **No official pre-T15 snapshot provenance**, no independent payout re-confirmation. Stakes are hypothetical ¥100 each.
- Seven fixed single-bet policies: model's most likely horse, market favourite, model's max probability x odds, maximum EV if >=2, maximum EV if >=3, longshot 10–50 odds and EV >=2, longshot 20–100 odds and EV >=2. None uses settlement results for selection.
- The model was previously selected on temporal log-loss, not ROI. Single-win policies are not the required two distinct ticket types.

## Results: hypothetical win odds, *NOT live ROI*

| Fixed research candidate | 2024 (2,191 valid-odds races) | 2025 (3,425) | 2026 (2,069) |
|:--|--:|--:|--:|
| Most probable model horse | 97.20% | 99.28% | 88.83% |
| Archived market favourite | 79.38% | 77.71% | 78.30% |
| Highest model probability x odds | 75.28% | 81.21% | 94.86% |
| Highest EV >=2 | 74.54% | 80.57% | 93.73% |
| Highest EV >=3 | 70.49% | 132.48% | 76.38% |
| Odds 10–50 and EV>=2 | 71.30% | 84.45% | 103.00% |
| Odds 20–100 and EV>=2 | 53.71% | 83.48% | 108.91% |

2025's isolated ROI >100% among EV>=3 is not replicated in 2024/26. 2026's slightly >100% longshots drop below 100% after removing largest hit (97.85% and 99.17%). These observations refute the claim that the tested win-only mechanisms are sustainably 400%; they do not prove no other mechanism can achieve it.

## Binding prohibitions
- No result here can be called actual site ROI, official T-15 ROI, two-distinct-type ROI, a profitable production model or proof of future performance.
- The production model, selection count, current bets, Workers, GitHub main and D1 remain untouched.
- Avoid searching more thresholds on these inspected years and claiming selected 400% as untouched performance.
- Future pre-T15 locked shadow candidates and actual JRA payouts are necessary to demonstrate any valid 400% approach.

**Promotion authorized: NO.**
