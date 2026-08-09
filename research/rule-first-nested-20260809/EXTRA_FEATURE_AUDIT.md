# Extra-feature / high-order rule audit

This continues the nested rule-first audit without changing the outer-test data after rule discovery.

Additional pre-race/static features tested:
- frame position / frame spread
- sex-age composition
- assigned-weight average/spread
- horse-weight average and weight change
- number of weight-gaining horses

Additional strictly historical/time-safe features tested:
- first-start count
- days since previous start
- prior same-surface experience
- prior same-distance-band experience
- prior same-venue experience
- previous finish band
- prior top-3 experience on same surface x distance band
- small previous-to-current distance-change count

The whole current date is feature-frozen before any same-date outcome updates are applied.

## Fold-1 train-only search
Two-to-five-condition search across 12 feature families produced zero rules passing the strong 200% durability gate.

Six-to-eight-condition interaction search produced four candidates total, of which two were strict and two fallback. Their train ROI -> untouched next-period ROI:
- 309.68% -> 46.62%
- 208.00% -> 50.39%
- 227.09% -> 116.32%
- 219.95% -> 29.22%

Union of the four on the untouched next period:
- 871 tickets
- 34 hits
- ROI 52.12%
- max-one-hit-removed ROI 47.38%

Conclusion: adding these unused physical/rest/course-history features and higher-order 6-8 condition interactions does not rescue the 200% rule hypothesis under honest forward evaluation.
