#!/usr/bin/env python3
"""Block silent divergence between the frozen model contract and live ticket selector.

Static implementation parity is not out-of-sample ROI validation.
No D1, no network, no data mutation.
"""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
cfg = json.loads((ROOT / "config/ten-year-completed-model.json").read_text(encoding="utf-8"))
assert cfg["ticketPolicy"]["equivalentScoreFormula"] == "ln(predictedProbability) + 0.4 * ln(officialJraOdds)"
assert cfg["ticketPolicy"]["candidateGeneration"].lower().find("top five") >= 0
typescript = (ROOT / "src/v1/completed-ticket-runtime.ts").read_text(encoding="utf-8")
python = (ROOT / "scripts/generate-ten-year-live-bets.py").read_text(encoding="utf-8")
assert re.search(r"COMPLETED_ODDS_SCORE_POWER\s*=\s*0\.4\s+as const", typescript)
assert re.search(r"ODDS_SCORE_POWER\s*=\s*0\.4\b", python)
assert "candidates.slice(0, 5)" in typescript
assert "candidates=candidates[:5]" in python
assert "b.predictedProbability * b.officialOdds - a.predictedProbability * a.officialOdds" in typescript
assert "-x['predictedProbability']*x['officialOdds']" in python
for source in (typescript, python):
    assert "Math.log(ticket.recencyFactor ?? 1)" in source or "math.log(x.get('recencyFactor',1.0))" in source
print("FROZEN_MODEL_TICKET_IMPLEMENTATION_PARITY_OK")
