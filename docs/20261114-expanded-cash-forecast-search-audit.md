# 2026-11-14 race-tantei: broad cash-ROI prediction-method search

**Status: no qualified model found. Read-only research; production unchanged.**

The criterion for naming or shipping a model is a cash-settled, time-locked betting ledger with (1) ROI >=200%; (2) ROI >=200% after removing the *single largest paid race* while retaining stakes; (3) hit races >=20%; (4) at least 3 bought races for every venue-day; and (5) an untouched later period meeting the same rules, using genuinely pre-T15 official inputs. A successful CI run is **not** a successful model.

## New independent research avenues executed

| Method family | Actual methodology | Search space | Code/Actions | Qualifying development models |
| --- | --- | ---: | --- | ---: |
| v6 dynamic two-expert cash portfolios | Chooses two different history-trained ticket-generating algorithms per venue/month using previous payouts; combines tickets and settles duplicate race IDs once, with flexible yen allocation | 672 base experts; **12,960 dynamic cash method compositions** | [Run #43584384795](https://github.com/race-tantei-lab/race-tantei/actions/runs/43584384795), successful | **0** |
| v7 cash-action rank spectrum | Generates fundamentally different buy tickets by selecting ranks 1st/2nd/4th/8th/16th/32nd/64th/128th/256th/512th/last among 765 predicted-cash actions, and varies race-slate order | **3,168** actually executed different variants | [Run #43584754216](https://github.com/race-tantei-lab/race-tantei/actions/runs/43584754216), successful | **0** |
| v8 independent horse-form payout learning | Two-stage LightGBM directly trained on runner history and real monetary win-severity payouts, not on horse-win classification accuracy. Train 2017-21, optimize *whole* 2022-24 validated cash, test 2025-26Apr only after development-qualified. Six markets, varied payout strengths, stakes, pairings, seasonal switches | 32 pre-race/context features, 26,486 race source rows, **12,150,000 mathematically represented seasonal allocations** (not 12,150,000 separately measured models) | [Run #43585172506](https://github.com/race-tantei-lab/race-tantei/actions/runs/43585172506), successful | **0** |

These are substantially distinct research families, rather than simply changing the number of historical months in the same 72-condition re-ranker. No model was promoted or back-filled into historical live bets.

## Integrity check of the historical payout mirror

[Read-only coverage audit #43585426317](https://github.com/race-tantei-lab/race-tantei/actions/runs/43585426317) independently recomputed the 2015-Apr 2026 top-10-ranked actual six-market payout matrix and compared the **same January-April season**:

- 2025 Jan-Apr: 1,001 included races, favorite-win flat ¥100 policy ROI **84.42557%**, win market had a payout among rank-10 tickets in **97.30270%** of races.
- 2026 Jan-Apr: 765 included races, same fixed policy ROI **75.25490%**, win market positive among rank-10 tickets in **96.33987%** of races.
- 2025 vs 2026: wide positive race coverage **99.20080% vs 98.69281%**, quinella **91.90809% vs 91.37255%**, trifecta **83.01698% vs 86.27451%**.
- The audit found **no severe payout coverage collapse** accounting for earlier low-model returns. These are third-party labels, **not** proof that all monetary fields have been officially reconciled.

2026 April's dataset is incomplete compared with a full year's coverage: the research mirror has 765 races from Jan-Apr, and 2026 May-Jul are absent. The crucial 2026 Aug-Nov live period is **not** included in these three research runs; it cannot legitimately be treated as independently passed.

## Material bottleneck beyond the searched algorithms

Research uses completed-race **final win odds**, which can be later than the operational T-15 lock. JRA-VAN's historical **time-series** odds product covers win/place/bracket/quinella only; wide, exacta, trio and trifecta require capture during the relevant live race period. Historical final odds are **not a substitute** for buyable odds at the decision time.

Public specification references:
- https://jra-van.jp/dlb/sft/lib/jv_odds_visualizer.html
- https://developer.jra-van.jp/t/topic/872

A profitable backtest without correct pre-T15 quotes and independent payout verification would not satisfy production requirements, even if this or another finite method search numerically crosses 200%. Conversely, these zero results do not prove that no valid model exists anywhere in the open-ended space of possible algorithms.

## Files and promotion state

- v6: `scripts/research-20261114-online-two-expert-cash-v6.py` on `research/20261114-online-cash-two-expert-v6`
- v7: `scripts/research-20261114-cash-rank-spectrum-v7.py` on `research/20261114-cash-ticket-rank-spectrum-v7`
- v8: `scripts/research-20261114-form-ml-cash-v8.py` on `research/20261114-form-ml-3year-forward-v8`
- Source integrity: `scripts/audit-20261114-cash-source-year-integrity.py` on `research/20261114-source-cash-integrity-audit`

**Models admitted = 0. Merged to main = no. Deployed = no. Official T-15/live 2026 Aug-Nov admission = not verified.**
