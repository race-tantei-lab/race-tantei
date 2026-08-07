import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts" / "search-runner-residual-walkforward.py"

spec = importlib.util.spec_from_file_location("runner_residual_search", TARGET)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.SEED = 20260808
module.FAMILIES = module.FAMILIES[::6]


def ticket_structure(course, roles):
    A, B, C, D = roles[:4]
    if course == "ライト":
        return [
            ("単勝", (A,)),
            ("ワイド", (A, B)),
            ("ワイド", (A, C)),
            ("ワイド", (B, C)),
            ("馬連", (A, B)),
            ("馬連", (A, C)),
        ]
    if course == "スタンダード":
        return [
            ("単勝", (A,)),
            ("単勝", (B,)),
            ("ワイド", (A, B)),
            ("ワイド", (A, C)),
            ("ワイド", (A, D)),
            ("ワイド", (B, C)),
            ("馬連", (A, B)),
            ("馬連", (A, C)),
            ("馬連", (B, C)),
            ("馬単", (A, B)),
            ("馬単", (B, A)),
            ("馬単", (A, C)),
            ("3連複", (A, B, C)),
            ("3連複", (A, B, D)),
            ("3連複", (A, C, D)),
        ]
    return [
        ("単勝", (A,)),
        ("ワイド", (A, B)),
        ("ワイド", (A, C)),
        ("馬連", (A, B)),
        ("馬連", (A, C)),
        ("馬単", (A, B)),
        ("馬単", (B, A)),
        ("馬単", (A, C)),
        ("3連複", (A, B, C)),
        ("3連複", (A, B, D)),
        ("3連複", (A, C, D)),
        ("3連単", (A, B, C)),
        ("3連単", (A, C, B)),
        ("3連単", (B, A, C)),
        ("3連単", (B, C, A)),
        ("3連単", (A, B, D)),
    ]


module.ticket_structure = ticket_structure
module.main()
