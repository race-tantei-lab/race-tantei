#!/usr/bin/env python3
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'scripts/research-evaluate-continuous-market-value.py'
spec=importlib.util.spec_from_file_location('market_base_scratchsafe',BASE)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

_original_prepare=mod.prepare_market_candidates


def prepare_without_nonbettable_runners(rows,odds_row,key_stats,bet_stats):
    win=(odds_row.get('officialOdds') or {}).get('win') or {}
    allowed=set()
    for horse,value in win.items():
        odd=mod.midpoint(value)
        if odd is not None and odd>=1.0:
            try:allowed.add(int(horse))
            except Exception:pass
    if len(allowed)<3:
        raise RuntimeError(f'OFFICIAL_BETTABLE_FIELD_TOO_SMALL:{len(allowed)}')
    filtered=[]
    for t in rows:
        horses=[int(h) for h in (t.get('horses') or [])]
        if horses and all(h in allowed for h in horses):
            filtered.append(t)
    if len(filtered)<3:
        raise RuntimeError(f'TOO_FEW_BETTABLE_CANDIDATES:{len(filtered)}')
    return _original_prepare(filtered,odds_row,key_stats,bet_stats)

mod.prepare_market_candidates=prepare_without_nonbettable_runners
mod.main()
