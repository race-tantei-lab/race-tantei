#!/usr/bin/env python3
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
cfg=json.loads((ROOT/"config/ten-year-completed-model.json").read_text(encoding="utf-8"))
audit=json.loads((ROOT/"analysis-results/ten-year-model-completion-20260812.json").read_text(encoding="utf-8"))
live=(ROOT/"src/v1/completed-worker-live-lock.ts").read_text(encoding="utf-8")
guard=(ROOT/"src/v1/completed-worker-deadline-guard.ts").read_text(encoding="utf-8")
policy=(ROOT/"src/v1/completed-prediction-policy.ts").read_text(encoding="utf-8")
hist=(ROOT/"scripts/build-ten-year-public-history-assets.py").read_text(encoding="utf-8")
py=(ROOT/"scripts/generate-ten-year-live-bets.py").read_text(encoding="utf-8")
expected="63e35910123b6b187b6f29a6036e2362a6a6f1fd15e331525dd5e323ada453a5"
assert cfg["runnerProbabilityModel"]["modelWeightsSha256"]==expected
assert abs(float(audit["full"]["roiPct"])-431.6505899903346)<1e-9
for needle in (
    "{ includeHistoricalDelta: true, includeSameDayDelta: false }",
    "const weights = normalizeCompletedWeights(raw);",
    "weights,\n    fetched.rows,\n  );",
    "predictionPolicy: COMPLETED_PREDICTION_POLICY",
):
    assert needle in live, needle
for forbidden in ("loadCompletedRecencyLearning(", "completedRecencyBetFactor(", "runnerFactors[index]"):
    assert forbidden not in live, forbidden
assert 'COMPLETED_PREDICTION_POLICY = "completed-4317-v1"' in policy
assert "snapshot.predictionPolicy !== COMPLETED_PREDICTION_POLICY" in guard
for needle in (
    "candidates.append((pr*ov,c,ov,pr))",
    "math.log(pr)+0.4*math.log(ov)",
):
    assert needle in hist, needle
for forbidden in ("live-recency-learning", "recencyFactor", "same_day"):
    assert forbidden not in py, forbidden
print("COMPLETED_4317_PARITY_OK roi=431.6505899903346 modelSha="+expected+" recency=false sameDay=false policy=completed-4317-v1")
