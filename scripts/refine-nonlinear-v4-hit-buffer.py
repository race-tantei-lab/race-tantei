from pathlib import Path

source_path = Path("scripts/refine-nonlinear-v4-allocation.py")
source = source_path.read_text(encoding="utf-8")

old_filter = '''            if result["hit"] < v4.REQUIRED_HIT:
                continue'''
new_filter = '''            if (
                result["hit"] < 45.0
                or vector[0] == 0
                or vector[1] == 0
                or vector[3] == 0
            ):
                continue'''
if old_filter not in source:
    raise RuntimeError("HIT_BUFFER_FILTER_PATCH_MISSING")
source = source.replace(old_filter, new_filter, 1)
source = source.replace(
    "Validation-only 10% allocation refinement for the fixed nonlinear v4 mixed portfolio.",
    "Validation-only allocation refinement with a 45% hit-rate buffer and mandatory dual-wide anchors.",
    1,
)
source = source.replace(
    "nonlinear-v4-allocation-refinement.json",
    "nonlinear-v4-hit-buffer.json",
    1,
)

namespace = {
    "__name__": "__main__",
    "__file__": str(source_path),
}
exec(compile(source, str(source_path), "exec"), namespace, namespace)
