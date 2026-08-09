# Frozen model: rule-first-20260809-rebuild

Status: ANALYSIS-ONLY / NOT DEPLOYED / FROZEN BEFORE 2026-08-08 HOLDOUT INSPECTION

Canonical bundle SHA256: `8ba42c8a3d4c01825d8c7a9180aa5b30bc0084c0470b3d9722b9db1efdbe5288`
Canonical bundle bytes: 67326
Base64 is stored as ordered parts `bundle.part.00` through `bundle.part.11`.

Restore:
```bash
cat bundle.part.* > frozen_rule_first_20260809.tar.gz.b64
base64 -d frozen_rule_first_20260809.tar.gz.b64 > frozen_rule_first_20260809.tar.gz
sha256sum frozen_rule_first_20260809.tar.gz
mkdir restored && tar -xzf frozen_rule_first_20260809.tar.gz -C restored
```

Bundle contents:
- `consolidated_rules_v2.json` — canonical 419 deduplicated strict rules
- `final_model_summary_v2.json` — exact backtest/robustness results
- `freeze_policy_v2.json` — immutable live selection and allocation policy
- `FREEZE_MANIFEST_v2.json` — input hashes and frozen file hashes
- `README_FREEZE_v2.md` — human-readable specification
- `source_scripts/rebuild_rules_stage1.py`
- `source_scripts/build_history_ticket_features.py`
- `source_scripts/build_consolidated_v2.py`
- `source_scripts/search_race_penalty_v2.py`
- `source_scripts/final_audit_v2.py`

Identity:
- Strict rules: 419
- Fixed DB: 7,695 races / 642 venue-days / through 2026-08-02
- Exactly 5 selected races per venue-day in historical audit: 3,210 races
- No fixed number of bet types; all six JRA bet types allowed
- Per-race budgets: 2,000 / 5,000 / 10,000 yen, 100-yen units
- 2026-08-08 is excluded from the fixed DB and had not been inspected when frozen.

Snapshot:
- Light 2,000: overall ROI 441.58%, max-one-payout removed 398.60%
- Standard 5,000: overall ROI 442.28%, max-one-payout removed 399.30%
- Premium 10,000: overall ROI 442.11%, max-one-payout removed 399.13%
- All three time periods > 200% for every course
- All five season-balanced folds > 200% for every course
