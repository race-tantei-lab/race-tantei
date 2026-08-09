# REJECTED AFTER TRUE HOLDOUT

The historical 419-rule rebuild in this directory **must not be promoted to production**.

It produced very high in-sample / non-nested robustness statistics, but the pre-locked 2026-08-08 true holdout had 15 selected races, 26 tickets, 0 hits, and 0% ROI on every course.

Root cause diagnosis: no direct target-race result-feature leakage was found, and payout mapping was later audited successfully. The failure is consistent with multiple-testing / rule-selection bias: rule discovery and robustness scoring repeatedly searched the same fixed history.

Use the nested/rolling research record under `research/rule-first-nested-20260809/` for the corrected methodology. Do not delete this rejected artifact; it is retained as an audit trail.
