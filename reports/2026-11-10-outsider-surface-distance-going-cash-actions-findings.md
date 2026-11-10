# Surface / distance / going: settled-cash extraction

- Verified 2026-11-10 GitHub Actions run: https://github.com/race-tantei-lab/race-tantei/actions/runs/42791381438
- Run conclusion: success; head SHA 07ed0e8dedc3a914889c1d2a72a7fae45d6b3b63.
- Artifact: outsider-surface-distance-going-sixmarket-cash-cells, ID 13751529375, expires 2026-12-10 09:33 UTC. Contains JSON and compressed CSV.
- Six-market scan on 2015-2022 historical data: 180 predefined schemas (30 per market). OUTSIDER_CASH_FINAL: historicalGross200=38, strictHistorical200=0. Three-fold market 3連複: 7,284,802 tickets, gross200=1, robust200=0. 3連単: 43,708,812 tickets, gross200=8, robust200=0.
- No training condition survived the robust 200% cash threshold, hence no candidate qualified for 2023/2024 forward testing; no adoption.
- Caveats: third-party settled payout CSV has not been independently reconciled with official JRA payouts; final win odds are not timestamped official T-15 odds; 2025/26 already researched, not pristine holdouts.
- Do not rerun this completed scan; next investigate genuinely new pre-race columns, verify temporal availability, and predefine finite condition space. Do not touch main/production.
