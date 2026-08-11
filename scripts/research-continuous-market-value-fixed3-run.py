#!/usr/bin/env python3
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'scripts/research-evaluate-continuous-market-value.py'
spec=importlib.util.spec_from_file_location('market_fixed3',BASE)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)


def select_fixed3(rows):
    if len(rows)<3:raise RuntimeError(f'TOO_FEW_ODDS_CANDIDATES:{len(rows)}')
    chosen=list(rows[:3]);types={t['bt'] for t in chosen}
    if len(types)<2:
        alt=next((t for t in rows[3:] if t['bt'] not in types),None)
        if alt is None:raise RuntimeError('NO_SECOND_BET_TYPE')
        chosen[-1]=alt
    chosen.sort(key=lambda x:(-x['marketScore'],-x['ev'],x['odds'],x['bt'],x['combo']))
    if len(chosen)!=3 or len({t['bt'] for t in chosen})<2:raise RuntimeError('FIXED3_GATE_FAILED')
    return chosen

mod.select_tickets=select_fixed3
mod.main()
