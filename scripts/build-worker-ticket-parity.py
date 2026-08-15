#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import itertools
import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "generate-ten-year-live-bets.py"
CORE = ROOT / "scripts" / "ten-year-production-core.py"
OUT = ROOT / "worker-ticket-parity.json"
BET_ORDER = ("単勝", "ワイド", "馬連", "馬単", "3連複", "3連単")


class NeutralLearning:
    @staticmethod
    def bet_factor(_state, _bet_type: str, _venue: str, _odds: float) -> float:
        return 1.0


def load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def positions(kind: str, n: int):
    if kind == "単勝": return itertools.combinations(range(n), 1)
    if kind in ("ワイド", "馬連"): return itertools.combinations(range(n), 2)
    if kind == "馬単": return itertools.permutations(range(n), 2)
    if kind == "3連複": return itertools.combinations(range(n), 3)
    if kind == "3連単": return itertools.permutations(range(n), 3)
    raise RuntimeError(kind)


def combo(kind: str, pos: tuple[int, ...], horses: list[int]) -> str:
    values = [horses[index] for index in pos]
    if kind in ("ワイド", "馬連", "3連複"):
        values.sort()
    return "-".join(map(str, values))


def main() -> int:
    generator = load(GENERATOR, "worker_ticket_parity_generator")
    core = load(CORE, "worker_ticket_parity_core")
    neutral_learning = NeutralLearning()
    rng = random.Random(20260815)
    cases = []
    for case_index in range(96):
        n = 3 + case_index % 8
        horse_nos = sorted(rng.sample(range(1, 19), n))
        raw = [rng.uniform(0.01, 2.0) for _ in range(n)]
        total = sum(raw)
        weights = [value / total for value in raw]
        odds = {}
        rows = []
        race_id = f"case-{case_index}"
        for bet_type in BET_ORDER:
            for pos in positions(bet_type, n):
                combination = combo(bet_type, tuple(pos), horse_nos)
                low = round(rng.uniform(1.1, 250.0), 1)
                high = low if case_index % 3 else round(low + rng.uniform(0.0, 10.0), 1)
                if high < low: high = low
                odd = (low + high) / 2.0
                odds[(race_id, bet_type, combination)] = odd
                rows.append({"betType": bet_type, "combination": combination, "oddsMin": low, "oddsMax": high})
        runners = [{"horseNo": horse_no} for horse_no in horse_nos]
        chosen = generator.choose_two(core, neutral_learning, race_id, runners, weights, odds, {}, "parity")
        cases.append({"id": race_id, "horseNos": horse_nos, "weights": weights, "odds": rows, "expected": chosen})
    OUT.write_text(json.dumps({"cases": cases}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"status": "TICKET_FIXTURE_OK", "cases": len(cases)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
