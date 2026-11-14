# Chronological cash-ROI audit — 2026-11-14

**Decision: NO ADOPTABLE MODEL FOUND. No production change.**

This report distinguishes the original look-ahead global venue-quarter optimizer from a genuinely chronological 2025–2026 holdout of its venue-quarter switching policies. It is an exploratory retrospective audit, **not prospective T−15 official-odds verification**.

## Data and procedure

- Research source: 136 monthly retrospective six-market JRA payout CSV files from the pinned public repository `Kenseimk/keiba-agent@f552ca8628646f39b05ffdbdc3ab8734939ffd66`. External source has not been independently reconciled to JRA on all races.
- 28,932 training races with race month through **2024-12**; 3,580 source races from **2025-01 through 2026-04** used solely for evaluation.
- The forecaster's per-race cash estimates update with strictly **previous-month** result information.
- For the method-switching policy, the MILP chooses exactly one fixed buying algorithm per venue × calendar quarter **from training-period outcomes only**. Those switches are frozen for the entire holdout.
- All purchased holdout races are accounted for. At least three races per venue-day; largest paid race is excluded *with its stake retained*.
- The independent artifact ledger was recalculated outside GitHub Actions: 2,362 purchased holdout races, ¥1,319,600 staked, ¥1,022,910 returned, **77.5167% ROI**, excluding largest returned race **29.8174%**, hit races **21.8036%**.

## Cash results

| Training cash objective | 2015–2024 training ROI | 2025–2026 holdout ROI | Holdout ROI excluding largest | Holdout hit rate | Qualified |
|---|---:|---:|---:|---:|---|
| profit weight 1.0 | 523.266% | 77.517% | 29.817% | 21.804% | **NO** |
| profit weight 1.2 | 523.266% | 77.517% | 29.817% | 21.804% | **NO** |
| profit weight 2.0 | 662.000% | 92.752% | 32.883% | 23.305% | **NO** |

First strategy annual cash ledger: 2025 **93.370% ROI**, largest excluded **32.431%**, hit **19.487%**; January–April 2026 **20.401% ROI**, largest excluded **19.972%**, hit **28.501%**.

## Why the previously reported 501.397% candidate cannot be promoted

The original `scripts/research-20261114-joint-all-history-money-milp.py` optimizes its 31 venue-quarter policies from the **same full 136 months** whose payout ROI it then reports. This is selection bias, even though each base forecaster had no same-month results.

An independent recomputation of that earlier 20,328-race payout ledger found:
- Whole archive 501.397% and 399.354% after excluding the largest paid race.
- **2025 only 161.521%, 97.227% without the largest**.
- Excluding the largest 20 paid races from the whole archive gives **154.375%** (stake retained).
- Only **42 of 136 months** individually reach 200% raw ROI.
- Results use retrospective final odds, **not recorded pre-T−15 odds**.

## Reproducibility

- [GitHub Actions run #43559966223](https://github.com/race-tantei-lab/race-tantei/actions/runs/43559966223) — **success**, tests passed, chronological split run.
- Action artifact ID `14099509636`: `20261114-chronological-joint-oos-2025-2026.json` and exact `...ledger.csv.gz`.
- Source `scripts/research-20261114-joint-cash-chronological-holdout.py` on `research/20261114-chronological-joint-cash-holdout`.
- Original apparent 501% in-sample artifact ID `14095055583`, verified separately.

**No completed ROI200 model, no merge to main, no changes to Cloudflare D1 or public tickets.**
