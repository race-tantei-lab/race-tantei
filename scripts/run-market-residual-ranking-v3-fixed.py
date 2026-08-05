from pathlib import Path

source_path = Path("scripts/train-market-residual-ranking-v3.py")
source = source_path.read_text(encoding="utf-8")

source = source.replace(".replaceAll(", ".replace(")
duplicate_marker = "model_selection + '  function buildBettingRecords('"
if duplicate_marker not in source:
    raise RuntimeError("MARKET_RESIDUAL_FIXED_RUNNER_MISSING_DUPLICATE_MARKER")
source = source.replace(duplicate_marker, "model_selection", 1)

if ".replaceAll(" in source or duplicate_marker in source:
    raise RuntimeError("MARKET_RESIDUAL_FIXED_RUNNER_PATCH_FAILED")

namespace = {
    "__name__": "__main__",
    "__file__": str(source_path),
}
exec(compile(source, str(source_path), "exec"), namespace, namespace)
