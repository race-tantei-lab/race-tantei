import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
SCRIPT_DIR = ROOT / "scripts"

workflow_hits = []
for path in sorted(WORKFLOWS.glob("*.yml")):
    text = path.read_text(encoding="utf-8")
    filename_versioned = re.match(r"^v\d", path.name, re.I) is not None
    named_versioned = re.search(r"(?im)^name:\s*V\d", text) is not None
    exploration_like = bool(re.search(r"(?i)(analysis|search|exploration|candidate)", text))
    if exploration_like and (filename_versioned or named_versioned):
        workflow_hits.append(str(path.relative_to(ROOT)))

script_hits = []
for path in sorted(SCRIPT_DIR.glob("analyze-v*.py")):
    text = path.read_text(encoding="utf-8")
    if "promotionEligible" in text or "ROI" in text or "roi" in text:
        script_hits.append(str(path.relative_to(ROOT)))

print(json.dumps({
    "activeVersionedExplorationWorkflows": workflow_hits,
    "legacyVersionedAnalysisScripts": script_hits,
}, ensure_ascii=False, indent=2))

if workflow_hits:
    raise SystemExit("ACTIVE_VERSIONED_EXPLORATION_WORKFLOWS_FOUND")
