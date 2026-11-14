# 2026-11-14 — Direct cash-method generation audit (research only)

**Outcome:** zero methods admitted as models under the user-defined constraints. Production unchanged.

## What changed from the previous 72-selector experiment

Previous adaptive-window PR #342 only chose among strategies supplied from elsewhere. It did **not** generate a ticket or a new cash-trained prediction procedure.

The new generators use the full 136-month (2015-01 to 2026-04) retrospective cash matrix, 32,512 finished races, six JRA markets and 1,030 possible ranked-horse combinations per race. Fifteen **causal previous-month-trained** historical cash predictors each generate one ticket per JRA market; a meta learner dynamically constructs/recombines cash ticket positions and chooses its underlying procedure based **only on past** ticket returns.

The action generator is not a hindsight optimization of one venue-quarter ticket rule. The generated parameter is kept stable, and each venue-day's tickets are determined using only earlier-month money.

## Actual code executed

| Experiment | Structures per race | Meta-method settings | Cash-stake rule | CI | Development qualified |
| --- | ---: | ---: | --- | --- | ---: |
| v2 initial | 225 (15 predictors × 15 pairs) | 1,512 | 2×¥100 | [run 43563677539](https://github.com/race-tantei-lab/race-tantei/actions/runs/43563677539) | **0** |
| v2 expanded | 225 | 4,032 | 2×¥1,000 | [run 43564076851](https://github.com/race-tantei-lab/race-tantei/actions/runs/43564076851) | **0** |
| v3 expanded | 765 (15 predictors × (6 singles + 15 pairs × 3 stake splits)) | 4,032 | ¥2,000/race; singles or 25/75, 50/50, 75/25 | [run 43564496459](https://github.com/race-tantei-lab/race-tantei/actions/runs/43564496459) | **0** |

All three GitHub Actions executions completed **successfully** as code runs. A successful job **does not imply a profitable model**.

**Method search dimensions:** historical horizons 3, 6, 12, 24, 36, 60 or 96 months; optional historic-cash-information embargo 0, 6, 12 or 24 months; pooled global / per venue / venue plus field-size context; payout caps, shrinkage and fresh predictor blend. The base 15 ticket predictors remain trained through the previous month; the lag applies to **cash meta-calibration**, and must not be inaccurately described as embargoing all underlying features.

## Model admission contract

Search on **2019-01..2024-12** (2015–18 as warmup). Only methods whose **entire development ledger** has ALL of:
- Actual payout-based cash ROI **≥200%**.
- Cash ROI **≥200% after removing the single largest paid race** while retaining its stake.
- Paid-race hit rate **≥20%**.
- At least **three different bought races every venue-day** (three or five selected per venue-day).

are passed to **2025-01..2026-04 independent holdout**. It is incorrect to name or list a method as an adopted model if either time-separated period fails.

No method crossed all mandatory gates on the development period, so **no model was created or serialised**, and the untouched holdout was not used to fish for a method. No percentages below 200% were reported as "models".

## Limits of evidence

- This is a finite method-generation space, not proof that profitable betting methods cannot exist.
- The 136-month research mirror is **third-party JRA-derived**, not fully independently matched to JRA.
- Historical input rank/odds derive from **retrospective final WIN odds**, not auditable official JRA T−15 snapshots. Therefore even a hypothetical research survivor would not yet be production eligible without official pre-lock odds verification and independent forward prospective tests.
- There is no deployment, D1 write, historical ticket rewrite, model promotion, or assertion of guaranteed future profit.

## Next methodological expansion

Instead of only adding more static thresholds, develop distinct **cash payout-generating forecasters** (not horse win accuracy classifiers), alternative structural ticket combinations and causal online portfolio policies. Every genuinely new search family must pass the same development / protected holdout / JRA T−15 gates before deployment.
