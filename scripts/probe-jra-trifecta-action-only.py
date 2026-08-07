import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "probe-jra-historical-trifecta-params.py"
OUTPUT = ROOT / "analysis-results" / "jra-trifecta-action-only-probe.json"

spec = importlib.util.spec_from_file_location("trifecta_action_source", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError("SOURCE_LOAD_FAILED")
source = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = source
spec.loader.exec_module(source)
collector = source.load_collector()
venue_html = collector.fetch_url(collector.JRA_ODDS_URL, cname=source.VENUE_DAY_CNAME)
actions = source.trifecta_actions(venue_html)
report = {
    "actionCount": len(actions),
    "targetRaceNo": source.TARGET_RACE_NO,
    "targetAction": actions[source.TARGET_RACE_NO - 1] if len(actions) >= source.TARGET_RACE_NO else None,
}
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, ensure_ascii=False))
