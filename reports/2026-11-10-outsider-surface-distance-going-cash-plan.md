# 2026-11-10 surface / distance / going cash-first exploration

Status: IMPLEMENTED; ACTIONS CASH SETTLEMENT NOT YET VERIFIED. Do not treat as completed research or adopted model.

Input audit: pinned Kenseimk/keiba-agent f552ca8628646f39b05ffdbdc3ab8734939ffd66 monthly race CSV header contains 距離, コース, 馬場状態, 斤量, 騎手, 調教師, 単勝オッズ, and six settled payout columns. Sample 202604 row has 距離=1200, コース=ダート, 馬場状態=稍重. Finishing position, final time, passing order, last 3F, and final payout are NOT allowed as pre-race features. The going field is from settled race data; independent verification of its availability at T-15 remains outstanding. Final win odds are NOT official T-15 snapshots.

Finite new search: four race-condition categorical axes (surface 2, distance 6, going 5, surface-distance 12); four singles, six new/new pairs and twenty new/old pairs, 30 schemas per market, 180 schemas across all six markets. Existing historical outsider ticket enumerator and ¥100 cash settlement are reused; old 878/594/240 schemas are not re-executed. Training 2015-22; later 2023, 2024, 2025 and 2026 Jan-Apr individually, only for robust historical survivors. Historical gross and maximum one race payout removed ROI are both recorded. Missing track data is excluded rather than imputed.

No outcome is claimed until Actions log, cash figures and artifact are verified. Research-only branch. No production changes.
