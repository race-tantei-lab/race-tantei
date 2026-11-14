# 2026-11-14 — Historical cash prediction model really refitted for each forecast month

## Work that was missing before

The user's suggestion was **not** to choose only among fixed conditions. It was to train the *ticket-money prediction algorithm itself* on different histories (e.g. last year only; last 3/6 months; training stopped one year ago), and possibly learn how to choose the prediction method dynamically. Previous v3-v9 variants mostly changed the pre-defined ticket method selector, not its underlying model training cutoff.

**This architectural requirement is now materially implemented and executed in v10/v11.**

For every target month, the v10 direct-conditional payout learner retrains empirical Bayesian expected monetary ticket returns for **all 1,030 six-market horse-rank tickets** using only payout records in its chosen history (3,6,12,24,36,60,96 months), with either zero or 12 months of information embargo. The model uses pre-result categorical odds, age, draw, field size, track, time-of-year and feature interactions. Ticket combination, market selection, money split and number of bets are generated from the newly fitted money predictor. 504 distinct complete direct forecasts and 72 online profit-selected approaches are evaluated by actual settled JPY amounts.

v11 extends the generator with **prospective venue-month abstention**, removing the earlier unjustified requirement to bet in every venue every day. The decision to participate uses only months already settled; every **active** venue-day must have 3 or more bought races. It searches both a base method with historic-ROI-conditioned participation and an adaptive cash forecaster with prior-money-based venue participation. A minimum of 80 bought development races/20 active venue-days and 24 independent holdout races/6 active venue-days prevents micro-sample payout artifacts.

## Verified GitHub Actions results

| Run | Numerical search | Actual run status | Qualifying 2017–2024 methods | Qualifying independent 2025–Apr2026 |
| --- | --- | --- | ---: | ---: |
| [v10 #43599185921](https://github.com/race-tantei-lab/race-tantei/actions/runs/43599185921) | 504 freshly trained direct-cash policies + 72 online selectors | **success** | **0** | **0** |
| [v11 #43599713192](https://github.com/race-tantei-lab/race-tantei/actions/runs/43599713192) | **28,224** independently scored prior-money venue-participation rules + **420** adaptive venue-selection methods, all based on the freshly trained v10 cash models | **success** | **0** | **0** |

The holdout is preserved: it is NOT mined for winner selection when zero development-eligible algorithms exist. No losing algorithm is emitted as a "candidate model" in machine output; `models: []`.

The full source archive covers **2015-01 to 2026-04**, 136 monthly files and ~32,512 races. Historical cash estimates are based on third-party JRA-derived settlement data with **final win odds** used for the horse-rank indexed templates. That archive **does not contain 2026 August-November** official pre-lock live snapshots, and historical win odds are not verifiable official odds at the T−15 betting deadline. Hence these reports cannot establish actual future tradability or live performance.

## Hard money qualifications

Every model must pass all of: `sum(JPY paid) / sum(JPY stake) >= 2`; `(sum(JPY paid) − largest paid SINGLE RACE) / sum(JPY stake) >= 2`; genuine paid-race hit >=20%; >=3 bought races each active venue-day, and sufficient active observations; validation/research period AND separate independent forward period. The largest payout is excluded **without** excluding its original stake. These are evaluated on settlement entries; refund classification in this third-party source has not been separately reconciled to JRA official records.

## Paths and promotion

- v10: `scripts/research-20261114-rolling-retrained-direct-cash-v10.py` on branch `research/20261114-rolling-retrained-cash-forecast-v10`.
- v11: `scripts/research-20261114-rolling-cash-selective-venues-v11.py` on branch `research/20261114-rolling-cash-selective-venues-v11`.
- Research-only GitHub Actions workflows for v10 and v11 are on their respective branches.
- No qualified model; no merge to main; no production deployment; no changing old or current actual predictions or cash ledgers.

**Research implementation and experiments succeeded; the required ROI200 profit-bearing production model is NOT complete.** The absence of a witness from these finite algorithm classes does not prove the absence of all possible profitable models.
