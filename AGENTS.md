# Instructions for all coding and research agents — レース探偵

**Read these before every change:** `HANDOFF.md`, `config/canonical-production-manifest.json`, and `docs/CURRENT_RESEARCH_EVALUATION_RULES_20261107.md`.

## Highest-priority user directives (2026-11-07)

- **Existing model is already built. DO NOT retrain or rebuild it from scratch.** Keep the deployed `ten-year-completed-model` 56-feature LightGBM / 500-tree weights, current runtime and existing recency behavior unless an explicit subsequent user instruction authorizes a model change. Improve prediction use, ticket ranking, calibration, official odds and settled bet portfolio using the existing model as starting point.
- **NEVER evaluate, recommend, or report hit rate WITHOUT ROI, or ROI WITHOUT hit rate.** Always present them **together** computed from identical frozen ticket/race cohorts, dates, budgets and actual JRA payouts. If one cannot be evaluated, plainly label the **paired result inconclusive**; do not celebrate or promote the other alone.
- **Do NOT limit ticket type exploration to win and wide.** Keep all SIX JRA bet types `単勝, ワイド, 馬連, 馬単, 3連複, 3連単` in the candidate universe, including all 15 pairs of distinct types and justified odds/combination/assignment strategies. Current production requires two different types per race; never change that without prior verification and explicit user direction.
- **At least 3 races per JRA venue/day, preferably 5 (the current production count).** Do NOT use zero, one or two races, retrospective cherry-picked selections or longshot-only jackpot strategies to manufacture ROI. Do not lower current 5-race production coverage just because research allows comparing 3, 4 and 5.
- **Optimise for BOTH broad, reliable race-hit coverage AND sustainable ROI; user aspirational ROI target is 400%.** No guaranteed 400% claim, no winner-picked-on-outcomes, no single giant payout passing as reproducible profit.
- Preserve **official JRA T−15 odds**, original model score and immutable pre-race tickets; settle with actual JRA payout only. Record late/missing/invalid races, both hit and ROI on same complete denominators. Group by month/venue and use genuinely prospective untouched races.
- **Research is not production.** No rewrite of prior public picks, D1 data, primary/backup Workers, site or currently deployed model because of an exploratory result. A passing research CI/test or PR is not proof of profitable live operation.

The older `docs/RACE_TANTEI_NON_NEGOTIABLE_RULES.md` and `config/race-tantei-fixed-constraints.json` contain pre-November 2026 research thresholds (such as ROI 200%, minimum 5 only). Preserve their historical meaning; **latest user research/reporting instructions above supersede only conflicting research thresholds, NOT actual current production safety and current 5-race implementation**.
