# 2026-11-14 — New prediction-method development: 10,692 cash-policy exploration, completed

**Final result: 0 methods satisfy the adoption threshold in the 2025 discovery period.** These are NEW proposed prediction policies, not retrospective validations of the existing 431%-ROI model.

All relevant jobs completed successfully after an aggregation bug was repaired and full cash-ledger checkpoints were persisted. An independent audit recomputed each policy's monetary admission using the cached data, rather than relying on model-learning logs.

## Search design

Freshly fit the original-style **56-column, 500-tree, 127-leaf LightGBM** every prediction month. The learning history is selected from **3, 6, 12, 24, 36, 60 or 96 months**, ending either directly before that target month or **12 months earlier**. Only outcomes *before* the selected training cutoff enter fitting. From each fresh model's runner probabilities, use the original Plackett–Luce market probability mathematics to generate two distinct ticket types among six JRA markets. Explore 15 market pairs, four within-market probability-ranked combinations, three cash splits, three/five races per entered venue-day and two race-ranking orders. This generates **10,080** fixed policy variants.

v13 also evaluates **36** dynamically selected previous-money alternatives. v14 builds a genuinely adaptive meta-model with **576** strategies: select the underlying cash model and relevant time horizon/venue/market pair again each month using only earlier settled yen cash, with market-family pooling and a prospective abstention decision.

Total distinct searched policy configurations: **10,080 + 36 + 576 = 10,692**.

## Financial gates — no losing models are emitted

For a method to become an admitted model, the entire **2025 development portfolio** must have all of:
- settled cash ROI at least **200%**;
- cash ROI still at least **200% after removing the single largest paid RACE** and keeping the entire stake;
- paid-race hit rate at least **20%**;
- at least **3 actually purchased races for every participated venue-day**;
- sufficient development sample (at least 25 participating venue-days).

Only a development-qualified method may be evaluated for independent **2026 Jan–Aug09** cash, requiring the same financial gates and at least 15 participating venue-days. Data from 2026 is never used to select methods or revise 2025 admission.

## Completed actual CI output

| Research | Actual successful run | Exhaustive generated policies | Development methods meeting all cash requirements | Independently admitted 2026 |
|---|---|---:|---:|---:|
| v13 fresh 56-feature six-market two-ticket forecasts | [Actions #43608026141](https://github.com/race-tantei-lab/race-tantei/actions/runs/43608026141) | 10,080 + 36 adaptive = **10,116** | **0** | **0 (none advanced)** |
| v14 online learned method-of-methods | [Actions #43608254340](https://github.com/race-tantei-lab/race-tantei/actions/runs/43608254340) | **576** | **0** | **0 (none advanced)** |
| Completely independent numerical count replay from both persisted cash ledgers | [Actions #43611122453](https://github.com/race-tantei-lab/race-tantei/actions/runs/43611122453) | **10,692** | **0** | **0** |

The independent audit verified:
- all 20 chronological target months from Jan2025 to Aug2026 represented;
- **280 genuine monthly LightGBM refits per run** (560 aggregate);
- all active venue-days at least three purchased races;
- all original and independent approval counts matched;
- the v13 and v14 cash-payout matrices were **byte-for-byte identical** across all checked cells (0 differences), ensuring the meta learner evaluated the intended same set of underlying forecasts.

## Explicit limitations — why this is NOT a universal proof or production completion

1. Research payout labels were JRA-derived D1 records for **2024-May to Aug2026**, with **8,570** six-market fully recorded races. The user-requested full 2017–2026 official monetary corpus was not available from this source.
2. Only **17 races** have recorded official time-stamped pre-T15 WIN odds; none covers a complete six-market historical T-15 period. Accordingly, all six-market ticket construction here is probability-ranked Plackett–Luce, **not a verified reproduction of market-price-aware tickets buyable before cutoff**.
3. The exact original 56-column training CSV expired; 34,566 races/478,682 runner feature rows were causally reconstructed, with unavailable historic weather/track/direction fields explicitly missing. Therefore this is not a byte-identical old production model, though the 500-tree LightGBM structure and feature names are used.
4. A small number of originally selected venue-days lacked complete matching D1 payout records; they were excluded from this **conditional** research sample with coverage diagnostics. The research audit does not claim all originally scheduled venue-days were assessed.
5. All methods failed to qualify in 2025, so **none** reached the 2026 independent acceptance gate. Do not treat "2026 admitted 0" as 10,692 independent holdout tests completed.
6. This finite class yielding 0 eligible methods **does not imply every possible profitable algorithm has been ruled out**.

**No new accepted or deployed profit model. No main branch merge, historical tip mutation, D1 writes or production deployment.** New algorithms and completed evidence remain on research branches and draft [PR #346](https://github.com/race-tantei-lab/race-tantei/pull/346).
