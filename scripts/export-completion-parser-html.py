import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts" / "validate-jra-historical-combination-parser.py"
OUT = ROOT / "artifacts" / "completion-parser-html"
OUT.mkdir(parents=True, exist_ok=True)

spec = importlib.util.spec_from_file_location("completion_parser_html", TARGET)
if spec is None or spec.loader is None:
    raise RuntimeError("VALIDATOR_LOAD_FAILED")
validator = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = validator
spec.loader.exec_module(validator)
collector = validator.load_collector()
venue_html = validator.fetch_retry(collector, validator.VENUE_DAY_CNAME)
actions = validator.actions_by_label(venue_html)
(OUT / "venue.html").write_text(venue_html, encoding="utf-8")
for label in validator.LABELS:
    cnames = actions.get(label) or []
    if len(cnames) < validator.TARGET_RACE_NO:
        continue
    cname = cnames[validator.TARGET_RACE_NO - 1]
    page = validator.fetch_retry(collector, cname)
    safe = label.replace("3", "three").replace("連", "ren").replace("単", "tan").replace("複", "fuku").replace("馬", "uma").replace("ワイド", "wide")
    (OUT / f"{safe}.html").write_text(page, encoding="utf-8")
print(str(OUT))
