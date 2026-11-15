# Frozen identity of the historical 716.827267% cash allocator (research only)

This record prevents accidentally substituting a different predictive model under the historical ROI label.

- **Research source:** `scripts/research-nov2026-canonical-cash-direct.py` at `research/nov2026-canonical-cash-direct-1112`, commit `dcb1c55900dcc95d0ada22af7dbbd772d9b86fc2`.
- **Successful source run:** https://github.com/race-tantei-lab/race-tantei/actions/runs/43233117016
- **Inputs:** exact frozen original 14,410 selected races (two distinct canonical tickets each) from `src/v1/ten-year-history-data`. NOT an independent horse/ticket prediction generator.
- **Financial fitting:** historic cash by **market + odds bin + race-number band**, return capped to JPY 30,000 per training ticket, Bayesian smoothing prior 40, cash ratio exponent 4.0, 2000 yen per selected race, 100 yen ticket stake increment, pick **3 of the canonical 5 per venue/day**, combined cash-priority rank.
- **Recipe frozen on 2021 and 2022 data**, re-fit cash groups from prior years for evaluation years.
- **2023–2026-08-09 combined:** 3,132 races, stake JPY 6,264,000, actual paid JPY 44,902,060, ROI **716.827267%**, largest single RACE payout removed keeping stake **705.052363%**, hit-race rate **54.469987%**.
- **Original source flags:** `researchOnly=true`, `eligibleForActualModelAdoption=false`, `sourceCandidateModelLookaheadRisk=true`, `sourceHistoryExactOfficialOddsTimestampT15NotVerified=true`, `unselectedRacesCannotGenerateNewTickets=true`.
- **Reason:** underlying original ticket candidates were trained on the entire retrospective 2016–2026 archive. Cash allocation is forward by year but the generator is NOT independently out-of-fold validated. No claim of prospective 716% returns is supported.
- **Known forward follow-up:** separately reported 2026-08-15–11-08 live-frozen replay ROI 58.94%, biggest excluded 52.08%; its exact source/denominator must be re-checked before treating as certified.

## Current rollback scope

PR #352 substituted truly independent `cash6`/`cash96` race + ticket generators into `/models/6m` and `/models/96m`. The safe revert restores those routes to the actual previously deployed PR #351 **research-only cash6/cash96 reweighting implementation**, and removes automatic 3-minute scheduling of the unvalidated independent prediction workers.

**IMPORTANT: the PR #351 cash6/cash96 pages are NOT this 716.827267% research allocator.** The allocator was never deployed, so describing restoration of pre-#352 pages as restoration of the 716% live model would be false. Do not rename the returned 6m/96m pages as the 716% model, or represent its 2023–26 backtest as live performance. Separate user approval and faithful historical-parity plus pre-T15 prospective backtesting would be required before activating the 716% allocator in production.

Preserve original current production `/` and `/races/:id`, all existing canonical frozen bets, model, and D1. Never re-write historical selections.
