from pathlib import Path

source_path = Path("scripts/train-market-residual-ranking-v3.py")
source = source_path.read_text(encoding="utf-8")
source = source.replace(".replaceAll(", ".replace(")
source = source.replace(
    "model_selection + '  function buildBettingRecords('",
    "model_selection",
)
namespace = {
    "__name__": "__main__",
    "__file__": str(source_path),
}
exec(compile(source, str(source_path), "exec"), namespace, namespace)
