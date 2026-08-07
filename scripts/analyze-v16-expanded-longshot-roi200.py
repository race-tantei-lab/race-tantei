import itertools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "analyze-v15-two-stage-roi200.py"
source = SOURCE.read_text(encoding="utf-8")

source = source.replace(
    'V15_OUTPUT = ROOT / "v15-two-stage-roi200-search.json"',
    'V15_OUTPUT = ROOT / "v16-expanded-longshot-roi200-search.json"',
    1,
)
source = source.replace(
    'v14.MODEL_VERSION = "v15-two-stage-hit-payout-roi200"',
    'v14.MODEL_VERSION = "v16-expanded-longshot-two-stage-roi200"',
    1,
)
source = source.replace(
    'v14.MAX_TRAIN_ROWS_PER_TYPE = 180_000',
    'v14.MAX_TRAIN_ROWS_PER_TYPE = 220_000',
    1,
)
source = source.replace(
    'v14.MODEL_PRIOR_WEIGHTS = (0.75, 0.90, 1.0)',
    'v14.MODEL_PRIOR_WEIGHTS = (0.85, 1.0)',
    1,
)
source = source.replace(
    'v14.ALLOCATION_POWERS = (1.0, 2.0, 4.0, 8.0)',
    'v14.ALLOCATION_POWERS = (2.0, 4.0, 8.0)',
    1,
)
source = source.replace(
    'v14.RACE_SCORE_MODES = ("minimum", "mean", "lower_mean", "light")',
    'v14.RACE_SCORE_MODES = ("minimum", "lower_mean", "mean")',
    1,
)

needle = '''if not hasattr(v14.v7, "month_sequence"):\n    v14.v7.month_sequence = v14.v7.v7.month_sequence\n'''
replacement = needle + '''\n\ndef expanded_primitive_catalog():\n    rows = []\n    for rank in range(1, 13):\n        rows.append((f"S{rank}", "単勝", (rank,)))\n    for first, second in itertools.combinations(range(1, 9), 2):\n        rows.append((f"W{first}{second}", "ワイド", (first, second)))\n        rows.append((f"Q{first}{second}", "馬連", (first, second)))\n    for first, second in itertools.permutations(range(1, 7), 2):\n        rows.append((f"E{first}{second}", "馬単", (first, second)))\n    for ranks in itertools.combinations(range(1, 8), 3):\n        rows.append(("T" + "".join(map(str, ranks)), "3連複", ranks))\n    for ranks in itertools.permutations(range(1, 7), 3):\n        rows.append(("X" + "".join(map(str, ranks)), "3連単", ranks))\n    return rows\n\n\nv14.base.PRIMITIVES = expanded_primitive_catalog()\nv14.base.PRIMITIVE_INDEX = {row[0]: index for index, row in enumerate(v14.base.PRIMITIVES)}\nv14.base.TYPE_BY_INDEX = {index: row[1] for index, row in enumerate(v14.base.PRIMITIVES)}\n'''
if needle not in source:
    raise RuntimeError("V16_INJECTION_POINT_MISSING")
source = source.replace(needle, replacement, 1)
source = source.replace(
    '"modelVersion": v14.MODEL_VERSION,\n    "report": str(V15_OUTPUT.name),',
    '"modelVersion": v14.MODEL_VERSION,\n    "primitiveCount": len(v14.base.PRIMITIVES),\n    "report": str(V15_OUTPUT.name),',
    1,
)

namespace = {
    "__name__": "__main__",
    "__file__": str(SOURCE),
    "itertools": itertools,
}
exec(compile(source, str(SOURCE), "exec"), namespace, namespace)
