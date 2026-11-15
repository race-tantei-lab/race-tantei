# 2026-11-14: Current original 56-feature model versus rolling retraining

**Decision: no model validated for deployment. All changes in draft PR only.**

## Original frozen model — auditable but in-sample
[Historical recomputation, Actions #43602734817](https://github.com/race-tantei-lab/race-tantei/actions/runs/43602734817) confirms 14,410 races, 2,882 venue-days (five per day), ¥28,820,000 staked and ¥124,401,700 returned: ROI **431.65059%**, ROI excluding the single largest paid race **429.90042%**, and hit rate **54.40666%**. The 2017–Aug2026 subset gives ROI **426.45202%**. However, the original LightGBM was fitted on the same full ten-year archive, so these numbers **are not out-of-sample performance**.

## Recovered 56-column training schema, with explicit gaps
[Source artifact check #43601176755](https://github.com/race-tantei-lab/race-tantei/actions/runs/43601176755) confirmed original canonical features artifact 9087261097 returns 404. [D1 archive census #43601427366](https://github.com/race-tantei-lab/race-tantei/actions/runs/43601427366) contains only 7,863 races May2024–Aug2026, not the original decade. [Reconstruction #43601867064](https://github.com/race-tantei-lab/race-tantei/actions/runs/43601867064) rebuilt **34,566 races / 478,682 runner rows / 14,410 legacy selected races** using preceding-day-only results. Pre-2024 weather, track, direction and complete T−15 odds are unavailable; these rows do not match original features byte-for-byte.

Read-only D1 official-recorded WIN cash [export #43602037563](https://github.com/race-tantei-lab/race-tantei/actions/runs/43602037563) obtained 8,570 payout race IDs. [Join audit #43603432418](https://github.com/race-tantei-lab/race-tantei/actions/runs/43603432418) matched **915** originally selected 2024 races, **1,430** in 2025 and **872** in 2026, out of 1,440 original 2025 selections and 900 through Aug2026. Missing payout observations cannot be silently fabricated.

## Actual 56-feature model retraining — completed
[Chronological training run #43602513826](https://github.com/race-tantei-lab/race-tantei/actions/runs/43602513826) passed and truly refitted LightGBM monetary bet selection across 3/6/12/24/36/60/96 preceding months and 0/12-month information embargoes. **280 monthly LightGBM fits** and **168 cash betting policies** were evaluated. Research pilot uses 300 trees/63 leaves versus the original 500 trees/127 leaves. Development: **2025 full year**; holdout: **Jan–Aug09 2026** only for development-eligible policies. **2025 cash admission count: 0; no model advanced to 2026 holdout.** This is not evidence that no valid betting model exists, nor does win-only research reproduce the original six-market two-ticket strategy. The final WIN odds are retrospective, not buyable official pre-T15 prices.

## Actual forward operation
[Aug–Nov read-only production audit #43603094868](https://github.com/race-tantei-lab/race-tantei/actions/runs/43603094868) checked **355** original model-selected races through Nov13. **251** had complete on-time locked and settled D1 tickets; **87** were missing, **17** late. On auditable Light tickets: **¥502,000 staked / ¥334,100 returned = 66.55% ROI**. A full 355-race ROI cannot be certified; source payouts are not independently reconciled.

No 200%-plus qualified new model; no main merge, no production deployment, and no database or historical-bet modification. The new 56-feature research pipeline is usable for further work, but the complete 2017–2026, official pre-T15, all-market profit target has **not** been achieved.
