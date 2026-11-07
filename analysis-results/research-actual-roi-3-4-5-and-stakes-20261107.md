# Research ROI audit — 2026-11-07 (READ ONLY, NOT APPROVED FOR PRODUCTION)

## Purpose and immutable boundary
Re-evaluate results already stored from pre-T-15 original two-ticket bets, without rewriting bets, changing the deployed model, making D1 writes, or estimating missing JRA payouts. All findings are retrospective (already observed): do NOT classify any winning strategy or race count here as proven out-of-sample or promotion-ready.

## Actual race-count counterfactual: 2026-08-15 to 2026-11-07
GitHub Actions run: https://github.com/race-tantei-lab/race-tantei/actions/runs/42364657648
- Dataset: original 5 selected races per venue, ranked by the **stored pre-race raceScore**; 68 venue-days with 340 originally chosen races.
- Top 3 per venue: 204 planned, **143 verified T-15 settled**, 61 missing/invalid; stake ¥286,000, return ¥188,200, **ROI 65.80%**.
- Top 4 per venue: 272 planned, **192 verified T-15 settled**, 80 missing/invalid; stake ¥384,000, return ¥284,200, **ROI 74.01%**.
- Top 5 per venue: 340 planned, **236 verified T-15 settled**, 104 missing/invalid; stake ¥472,000, return ¥309,800, **ROI 65.64%**.
- Invalid reasons in 5R dataset: 87 races lacking exactly two bets; 17 with late/unverifiable T-15 lock.
- These ROIs are *on valid placed bets only*. They do **not** include imaginary stakes or payoffs on missing bets and are not complete operational ROI.

### Strictly paired **same complete venue-days**
GitHub Actions run: https://github.com/race-tantei-lab/race-tantei/actions/runs/42364850034
- Require ALL FIVE original races on the same date+venue to have exactly two immutable, valid, on-time, settled Light-course tickets. 33 complete venue-days over 16 dates.
- 3R: 99 races, stake ¥198,000, return ¥127,600, **ROI 64.44%** (58.89% after keeping stake and removing the largest race payout).
- 4R: 132 races, stake ¥264,000, return ¥172,800, **ROI 65.45%** (61.29% trimmed).
- 5R: 165 races, stake ¥330,000, return ¥191,700, **ROI 58.09%** (54.73% trimmed).
- Date-cluster 10,000-replicate descriptive bootstrap for 4R minus 5R: **+7.36 percentage points**, 95% interval **[-1.88, +13.94]**. For 3R minus 5R: +6.35 points, 95% interval [-5.96,+18.82]. Neither proves the smaller count's advantage.
- The rank 2 slot's observed payout can exceed rank 1 on this *small* cohort; cherry-picking rank 2 **after results are observed is prohibited**.

### Monthly out-of-time stability check
Using all valid original top-k bets (different missingness across k):
- August 2026: k3 57.34%, k4 94.88%, k5 85.87%.
- September 2026: k3 60.89%, k4 82.69%, k5 68.62%.
- October 2026: k3 67.68%, k4 61.41%, k5 55.60%.
- November 1 and 7, 2026: k3 85.71%, k4 71.05%, k5 64.29%.
All observed monthly k variants lose money. As the historical 2026 returns were already studied, none of these months is a truly untouched validation after this research.

## Existing 8-stake-allocation walk-forward diagnostic
Prior independent, **read-only** GitHub Actions run: https://github.com/race-tantei-lab/race-tantei/actions/runs/42354992276
- 340 original selected races, 236 valid T-15 locked settled races.
- Eight predeclared allocations were evaluated across Aug/Sep exploration, October historical holdout, Nov 1/7 surveillance; NO October allocation exceeds 100% ROI.
- In October (116 valid races): equal 55.60%, nonwide 1900/100 56.84%, lower-odds 1800/200 68.16%. The 8-policy comparison was unsuccessful overall; do not select an October winner after inspection.
- Train-selected nonwide 1900/100 had Aug/Sep 95.59%, October 56.84%, November 92.14%, and entire 236 race sample 76.24%; it did not demonstrate profitable future returns.
- Bootstrap for October selected-vs-equal: +1.24 percentage points, 95% date-cluster interval [-7.75,+12.44], so no reliable improvement.

## Why historical 431.65% does not certify future profit
- 2016-08-10 through 2026-08-09, 14,410 old selected races, 431.65% retrospective in-sample ROI, from weights trained on same historical archive. Not out-of-fold.
- Trained-completed policy is EV top-five and score power 0.4; current deployed predecessor runtime is full-candidate power 0.2 after rollback. Misalignment requires an independently verified profitability investigation BEFORE touching production.
- Full historical six-bet-type official combination odds at the exact T-15 lock and full immutable feature context are not available for the needed multi-year untouched re-run. Do not substitute postrace odds or fake missing tickets.

## Decision
**NO candidate passed** stable, complete, honest ROI >100% with acceptable missingness, full temporal separation and unchanged constraints.

- k=3 and k=4 are useful predeclared research alternatives but **not production-authorized**.
- Reallocating existing ticket stakes does not resolve the model's negative ROI.
- Next viable causal test: preserve pre-T15 JRA odds, runner predictions and pre-race race score as immutable shadow predictions, then apply actual JRA settlements without optimization on the same dates, respecting the original 2-ticket budget. Consider also conditional no-bet, with separately reported race/venue coverage. Do not claim universal 5R is required if research proves fewer better.
- This audit must never be promoted to main as a change to the selection model, completed weights, ticket generation, live Workers or D1 history.
