import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT / "scripts" / "analyze-v14-historical-roi200.py"), run_name="__main__")
