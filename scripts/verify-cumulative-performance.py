#!/usr/bin/env python3
from pathlib import Path

root=Path(__file__).resolve().parents[1]
src=(root/"src/v1/cumulative-performance.ts").read_text(encoding="utf-8")
v37=(root/"src/public-site-entry-v37.ts").read_text(encoding="utf-8")
perf=(root/"src/public-site-entry-performance-history-fix-20260915.ts").read_text(encoding="utf-8")

required=[
    "races: 14410, stakeYen: 28820000, returnYen: 124401700",
    '{ venue: "東京", races: 2230, stakeYen: 4460000, returnYen: 17897900 }',
    '{ venue: "京都", races: 1705, stakeYen: 3410000, returnYen: 13982100 }',
    "r.race_date>? AND r.race_date<=?",
    "b.course='ライト'",
    "b.source_prediction_id=-2",
    "row.rowCount !== 2 || row.settledRows !== 2 || row.stakeYen !== 2_000",
    'CUMULATIVE_PERFORMANCE_STATE_KEY = "public_cumulative_performance:v1"',
    "EOD_FROM_MINUTE = 18 * 60 + 35",
    "EOD_THROUGH_MINUTE = 23 * 60 + 5",
]
for needle in required:
    if needle not in src:
        raise AssertionError("cumulative performance missing: "+needle)

for forbidden in ("tenYearRaces(", "date('now','-14 days')", "date('now','-30 days')"):
    if forbidden in src:
        raise AssertionError("cumulative performance broad/runtime history forbidden: "+forbidden)

for needle in (
    "loadCumulativePerformance(env.DB)",
    "累計回収率（ライト）",
    "会場別回収率（ライト）",
    "10年検証＋本番",
):
    if needle not in v37:
        raise AssertionError("home cumulative projection missing: "+needle)

for needle in (
    'url.pathname === "/api/public/cumulative-performance"',
    "refreshCumulativePerformanceIfDue(env, now)",
    "PUBLIC_CUMULATIVE_NIGHTLY",
):
    if needle not in perf:
        raise AssertionError("nightly cumulative integration missing: "+needle)

print("CUMULATIVE_PERFORMANCE_SAFETY_OK baseline=exact nightly=incremental light=2000")
