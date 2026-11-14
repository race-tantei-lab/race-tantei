# 2026-11-14: online cash-model discovery and chronological audit

## Decision

**NO ADOPTABLE MODEL IDENTIFIED. NO MAIN MERGE. NO PRODUCTION / D1 WRITES.**

This is an actual execution report, not a claim that the investment objective has been achieved.

### Nonnegotiable qualification gate

**Only** a chronologically precommitted predictor is eligible when its complete settlement ledger simultaneously meets:

1. Actual yen received / actual yen staked **≥200%**.
2. Subtract the *single largest paid race return* from aggregate yen receipts, **retain all stakes**, recalculate ratio: **≥200%**.
3. At least **20% of paid races** have winning cash returned; refunds should not be counted as wins when independently reconciled.
4. **At least 3 different races per venue/day** throughout the scored window.
5. Repeat on a **later, previously untouched period** with identical source rules; no looking up future payouts to choose a method.
6. All bought tickets and six-market odds must ultimately be audited against JRA **T-minus-15 official snapshots** before adoption.

Intermediate strategy arithmetic below all the criteria is *not a model*. A CI job succeeding merely means the experiment ran successfully; it is not proof of a winning model.

### Experiment v4: genuinely dynamic method-of-methods

- Base 672 cash action generators constructed from **765 per-race cash action structures**.
- 756 online selectors that dynamically choose the base ticket method per racing venue/month using **earlier** actual cash outcomes.
- Data: 136 monthly historical datasets, 2015-01 to 2026-04, ~32,512 races, six market payouts / 1,030 ranked-tickets possible per race.
- Development 2019-01 to 2024-12; 2025-01 to 2026-04 untouched unless a development-qualified model exists.
- **Development qualified 0, holdout qualified 0.**
- [Successful workflow run 43576395078](https://github.com/race-tantei-lab/race-tantei/actions/runs/43576395078), final marker `ONLINE_CAUSAL_META_CASH_SEARCH_FINAL`.

### Experiment v5: full 2017 start + adaptive bet size

- Keeps the 672 original cash ticket generators, **four cash stake-allocation methods** and **3,024 online prediction-method selectors**.
- Venue/month method, market combination, forecast history (3,6,12,24,36,60,96 months), historical cash lags, win-concentration penalty and **monetary stakes** change according to prior-month-only cash performance.
- The **final purchased stake is not fixed at ¥2,000**: each base ¥2,000 action is multiplied 1,2,3,4 or 5 times depending on chosen allocation and the earlier-month cash score.
- Development period **2017-01 through 2024-12** using 2015–16 as training history; protected independent test period **2025-01 through 2026-04**.
- Uses exact yen actually implied by the cash payout mirror, not horse win prediction, log-loss or win-probability classification.
- CI verified synthetic no-future-payout change invariants and the whole 136-month cash research run completed successfully.
- **Development qualified 0, independent holdout qualified 0, `models: []`.**
- [Successful workflow run 43576931954](https://github.com/race-tantei-lab/race-tantei/actions/runs/43576931954), final marker `ONLINE_CAUSAL_META_CASH_SEARCH_FINAL`.

### Important limitations

The current retrospective data is a *third-party JRA-derived settlement mirror* and post-race final **win** odds for popularity ranking. This is not itself an official JRA T-minus-15 observation. Therefore it is impossible to certify real production T-minus-15 betting profitability from this dataset alone.

The retrospective source ends in **April 2026**. The important **August–November 2026 actual live period** is *not included* in v4 or v5; it requires independent official D1 frozen-bet snapshots and settlement reconciliation before promotion. It would be misleading to call the v5 holdout "all of 2026".

Even exhaustive enumeration of this finite program class does **not** prove that no profitable model exists in the mathematically infinite space of possible betting programs. Nor can a user-selected required ROI be guaranteed from actual future race results.

**No ROI200 model was created, no prediction was promoted and no cash bet in production was changed.**
