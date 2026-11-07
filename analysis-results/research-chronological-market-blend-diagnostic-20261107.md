# Chronological OOS 56-feature model and non-T15 market benchmark (research only)

## Source
GitHub Actions successful execution (2026-11-07):
https://github.com/race-tantei-lab/race-tantei/actions/runs/42365008176

**Training/evaluation protocol**
- Feature dataset reconstructed only from 34,566 archived 2016-08..2026-08 JRA races; 34,512 races with a unique winner, 477,946 runner rows.
- Reconstructed *pre-result* horse/jockey/trainer history features in date order; do not load future final history state and do not feed archived odds or popularity into the 56 model features. Same-day history updates only after whole day.
- Missing historical race context (direction, conditions, weather, track state) means exact deployed production LightGBM feature parity is not established. Bodyweights also lack an independently confirmed T-15 capture time. This study is a **partial feature-family diagnostic, not proof for the production model**.
- Compare exactly two predeclared model complexities using 2024 and 2025 year-by-year historical forwards only, choose the 2024+2025 best log-loss, then train pre-2026 and evaluate Jan 1 through Aug 9 2026. Neither historical model candidate is production promoted.

### 56-feature model chronological result
- 2024: 3,448 race winners; original 500 trees/127 leaves: log-loss 2.1028868; top-pick 28.915%. Simpler 150 trees/31 leaves: log-loss 2.1153019; top-pick 28.451%.
- 2025: 3,449 race winners; original: log-loss 2.1223315; top-pick 27.544%. Simpler: log-loss 2.1362398; top-pick 28.153%.
- Original-complexity LightGBM selected on 2024+2025 log-loss ONLY (2.11261 vs simpler 2.12577).
- 2026 Jan-Aug: 2,152 races; original-complexity out-of-time log-loss **2.127249**, top-pick **26.022%**; 1/n uniform log-loss 2.6043961, chance top-pick 7.618%. **This proves nontrivial future predictive correlation versus uniform, not value or profit versus market.**

### Paired 2026 archived win-odds benchmark
On exactly the same 2,069 races with valid archived win odds (odds snapshot time is *not* verified as T-15):
| Winner probability baseline | Top pick winner % | Winner log-loss |
| --- | ---: | ---: |
| 0% model + 100% archived win-odds-implied market | 33.301 | 2.0512188 |
| 25% model + 75% market | 33.204 | **2.0390492** |
| 50% model + 50% market | 32.769 | 2.0468307 |
| 75% model + 25% market | 29.725 | 2.074212 |
| 100% model + 0% market | 26.196 | 2.1285424 |

**The 25% model mixture had the lowest log-loss in this ALREADY OPENED 2026 diagnostic, but this is NOT an untouched result after comparing mixture weights.** It must NOT be promoted or calibrated using these numbers, nor claimed profitable. Market favorite has a higher top-pick hit rate than each mix, whereas 25% model improves distributional log-loss relative to market only.

### Essential limitations for actual betting ROI
- Complete official JRA T-15 combination odds for all six ticket types, for all selected racing dates, were **not stored or independently recovered**. The available archived win odds are not guaranteed available at lock time.
- No comparable counterfactual ticket portfolio across six bet types can be audited honestly using these archives; **NO ROI for the blends is reported**.
- The 2026 analysis range has now been viewed. Future model evaluation must use new, immutable, before-event shadow predictions and a later racing period untouched by these model selection decisions. Never reframe the opened 2026 data as fresh holdout.
- The required two **distinct** ticket types and 3/4/5 selected races are not assessed by winner-prediction metrics. Other repository experiments separately measure real live locked-bet ROI, all losing at present.
- No model, policy, Worker, D1 table or historic ticket was altered.

**Decision: research-only; no profitable, temporally validated replacement model certified.**
