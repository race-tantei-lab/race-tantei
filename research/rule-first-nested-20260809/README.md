# Rule-first nested/rolling audit — 2026-08-09

Status: **research only / no production model frozen**.

## Why this exists
The earlier 419-rule rebuild produced ~442% historical ROI but failed the pre-locked 2026-08-08 true holdout at 0%. This research corrects the validation design by putting rule discovery itself inside each training window.

## Fixed data
- 7,695 JRA races: 2024-05-04 through 2026-08-02
- 24,042,050 valid official-odds tickets across six bet types
- 642 venue-days
- Current-race result/payout never used as a rule condition
- Horse/jockey/trainer history is updated only after current-race features are frozen

## Payout integrity audit
The ticket payout array contains exactly 61,732 positive tickets, equal to the 61,732 six-bet-type payout rows in the fixed DB. Sum of payouts is exactly 1,358,476,200 yen on both sides; maximum payout is exactly 58,367,060 yen; duplicate payout keys = 0.
For winning tickets, stored official-odds band versus payout-implied odds band agrees 95.0% overall: win 99.7%, quinella 99.4%, exacta 99.2%, trio 99.5%, trifecta 98.9%; wide 87.8% because a stored min/max range midpoint is used. This makes a broad ticket-to-payout misalignment very unlikely.

## Honest outer rolling results
Rule discovery occurs only inside the training prefix. The fixed application policy is then evaluated on untouched forward blocks.

Initial rule-score policy, Light ROI by outer fold:
- fold1: 50.18%
- fold2: 7.53%
- fold3: 52.56%
- fold4: 91.07%

Rule-preserving policy (buy all tickets matching the chosen rule), Light ROI:
- fold1: 58.48%
- fold2: 0.00%
- fold3: 56.14%
- fold4: 120.65%

Adding independent-hit-count durability did not repair fold1: Light 56.89%.
Adding time-safe OOF model/residual market-ratio and EV rule features produced zero rules passing the stronger train-only 200% durability gate in fold1.

## Rolling exact-rule recurrence
Seven discovery snapshots were built with training endpoints at blocks 3,4,5,6,7,8,9. A predeclared recurrence screen of >=4/7 snapshots, >=2/3 recent snapshots, and present in the latest snapshot retained 21 concrete rules. On untouched blocks 10-11 their union ROI was 72.49%, and only 22/114 venue-days had five recurrent-rule races available.

Several concrete rules nevertheless remained positive in two distinct forward intervals, including:
- Kyoto / quinella / 75-100x / 1300-1500m: 117.98% then 179.66%
- same core + jockey historical place-rate 25-35%: 174.00% then 334.30%
- Fukushima / wide / 30-50x / <=1200m / max popularity 12-14: 135.49% then 113.51%
- Kyoto core + trainer historical place-rate 25-35%: 132.03% then 129.87%
These are sparse and do not satisfy the all-venue five-race requirement by themselves. They are research candidates, not a validated production portfolio.

## Current conclusion
The fixed database demonstrably contains many retrospective 200%+ uniform rules, but the high historical ROI does **not** survive honest nested rule discovery. As of this audit, no model has demonstrated both:
1. five races on every venue-day, and
2. >=200% genuinely forward/nested ROI.

Do not claim completion until a future-unseen validation supports it. Do not tune on 2026-08-08; it is permanently retained as a failed true holdout.
