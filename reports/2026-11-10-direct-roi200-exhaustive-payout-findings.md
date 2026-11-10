# 2026-11-10: Direct settled-cash ROI200 condition enumeration (no prediction model)

## Verified execution
- GitHub Actions run: https://github.com/race-tantei-lab/race-tantei/actions/runs/42732365936 (success)
- Artifact: jra-all-patterns-direct-roi200-cash-extraction, id 13725128138, expires 2026-12-10
- Script: scripts/research-nov2026-exhaustive-roi200-cash-conditions.py
- Source: pinned public *third-party* CSV Kenseimk/keiba-agent f552ca8628646f39b05ffdbdc3ab8734939ffd66. Official JRA payout reconciliation incomplete.
- Final WIN odds from race results, **NOT** JRA T-15 official six-market odds.

## Search universe and chronological split
- 32,512 races: 2015–2022 historical discovery 23,274 races; 2023 2,852; 2024 2,806; 2025 2,815; 2026 Jan-Apr 765.
- 33,487,360 cash ticket candidates: every distinct six-market combination from the 10 runners with smallest archived FINAL WIN odds (1030 per eligible race).
- Exactly 878 categorical schema families: all 793 one- through four-way subsets of 12 predeclared core categorical features, plus 85 supplemental singleton / pairs. Every eligible category-value combination in these families enumerated using np.bincount on actual return yen. This is exhaustive **within the declared universe**, not all 18 runners, all possible features or continuous thresholds.
- No model trained, horse prediction metrics used or payout leak into discovery features. Distinct test years not used to pick initial ROI200 cash cells. NB the 2025–26 periods have been previously inspected in other research and are NOT pristine global holdouts.

## Direct extraction findings
- Historical cells with ≥20 ¥100 tickets and gross cash ROI ≥200%: **26,098** (overlap across schemas).
- Cells with ≥100 historical tickets, ≥5 paid tickets and ROI ≥200% even after subtracting all payouts from the single largest-paying race (while keeping original stakes): **974**.
- The same 974 historical-robust cells yielding ≥200% after removing the largest-paying race in each later period, with ≥10 tickets in that period:
  - 2023: **1 cell**
  - 2024: **33 cells**
  - 2025: **3 cells**
  - 2026 Jan-Apr: **0 cells**
  - **2023 AND 2024: 0 cells**
  - 2023, 2024, 2025, 2026 Jan-Apr all ≥200%: **0 cells**.
- Of the 974 historical strict cells, 309 trifecta, 259 exacta, 180 quinella, 170 trio, 40 WIN, 16 WIDE. These categories and overlapping schemas do not represent disjoint independent profits.
- 2026 Jan–Apr: 42 historical strict cells had gross ROI ≥200% with ≥10 tickets, but none maintained ROI ≥200% after removing its largest single paying race. This is one-way jackpot sensitivity, not stable profitability.
- Even with a weaker 50% max-race-trimmed ROI threshold in each of 2023, 2024, 2025 and 2026 Jan–Apr, ZERO of the 974 cells persisted across every period (≥10 tickets each).

## The one 2023 repeat, which collapses
Historical value: TRIFECTA, category bins `rankMin=3, rankFirst=4, oddsGeom=4, favGap=3`.
- 2015–2022: 3,306 tickets; stake ¥330,600, paid ¥948,670, gross ROI **286.954%**, max-paying-race removed ROI **235.088%**, just seven winning tickets.
- 2023: 428 tickets; stake ¥42,800, paid ¥223,140, ROI **521.355%**, largest race ¥114,330 excluded ROI **254.229%**.
- 2024: 336 tickets; stake ¥33,600, **paid ¥0**, ROI **0%**.
- 2025: 392 tickets; stake ¥39,200, paid ¥98,740 (ROI 251.888%), but **max-race removed ROI 0%**.
- 2026 Jan-Apr: 64 tickets; stake ¥6,400, paid ¥0.
This cell **fails** required year-to-year stability. Do NOT adopt or deploy.

## Research decisions
1. This experiment answers the user's requested **cash conditions first, prediction models later** question with recorded source cash and complete category enumerations. No cherry-picked model handwaves.
2. Reject the 974 historical-only conditions as independently demonstrated robust ROI200 strategies; the single 2023 repeat fails the next year. Do not promote based on 2024 alone.
3. Next expand the candidate universe beyond top-10 to outsiders (rank 11–18), new ex-ante race/form/payout-market feature families and genuine T-15 market prices where available. Enumerate cash-profit cells first, and only then design bets/portfolio combinations. Never rerun identical 878 schemas as if a fresh model.
4. No production main, Workers, D1 or public site change. Do not claim guaranteed 200% returns.

All 26,098 cells with historical cash amounts and forward-period metrics on historical-robust cells: the workflow artifact CSV.gz. Top strict 40 and strongest 2023 40: workflow artifact summary JSON.
