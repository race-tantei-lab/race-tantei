# Cash-first candidate audit (2026-11-12)

The question was whether discovering **zero** historic ROI >=200% systems from recent third-party payout mining justified dismissing old high-ROI findings. It did not.

## Same-source financial reconciliation

The canonical official-quote archival candidate ledger has 14,410 races across 2,882 venue-days with two distinct markets. An equal ¥1,000/¥1,000 per-race stake exactly reconciles 28,820,000 yen spent and 124,401,700 yen paid: ROI 431.6505898681471%.

We enumerated **18,900 cash-only policy recipes**, selected one using ONLY 2021-2022 money, and evaluated its frozen formulation with annually refreshed strictly prior-year cash cohorts on 2023 through 2026-08-09. The selected recipe pools by market x official odds band x race-number band, caps only historical cash-estimation contribution to ¥30,000, applies 40-ticket shrinkage, and allocates ¥2,000/race via 4th-power cash expected-return weights with ¥100 minimum/ticket. It buys three of the existing five candidates per venue-day.

Results: 3,132 races, ¥6,264,000 staked, ¥44,902,060 paid, **716.827267%** full-period ROI, **705.052363%** after removing the biggest paying race while retaining its stake, **54.469987%** hit races. All 2023, 2024, 2025, and 2026-to-Aug-9 calendar slices had ROI exceeding 200% after removing each year's largest paying race. The equal-stake baseline **on exactly the same race subset** is 488.818646%.

These exact values were reproduced in two separate successful GitHub Actions executions. Full cash ledger is downloadable from the respective run artifacts.

## CRITICAL: this is NOT an independently qualified production model

The two original candidate tickets per race were selected using a frozen historical model fitted to outcomes across the complete 2016-2026 archive. Optimizing only the *subsequent cash allocator* with prior-year money is insufficient to remove that fundamental look-ahead/selection bias. Neither an official T-15 quote timestamp for each historical candidate nor an unbiased candidate-generation walk-forward test has been established.

Current production code also uses odds exponent 0.2 plus online recency factors, whereas the archived historical 431.65% rule used exponent 0.4 without the same live adjustments. The historical candidate archive is not an exact evaluation of today's production predictor.

Therefore the historical cash ROI >=200% gates **PASS**, but the no-overfitting / live-equivalent evidence gate **FAILS**. Never merge to main, overwrite historical picks, or claim a newly adopted forward-effective 200%-ROI model on this evidence.

## Required next proof

Regenerate **candidate tickets themselves** with a model trained only on data before the betting lock, using the actual JRA official T-15 odds captured at the time. Freeze each race's two distinct market bets before result publication, then independently settle the actual yen ledger with no target-period retuning. Reconcile each JRA venue-day (>=3R), every calendar period, the largest race payout removed, and hit rate >=20%. An independently qualifying system can then be considered for release.