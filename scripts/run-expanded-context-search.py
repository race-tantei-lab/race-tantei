import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEARCH_PATH = ROOT / "scripts" / "analyze-expanded-context-search.py"

spec = importlib.util.spec_from_file_location("expanded_context_search", SEARCH_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("EXPANDED_CONTEXT_SEARCH_LOAD_FAILED")
search = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = search
spec.loader.exec_module(search)

if not hasattr(search.base_analysis.v7, "month_sequence"):
    search.base_analysis.v7.month_sequence = search.base_analysis.v7.v7.month_sequence

search.main()
