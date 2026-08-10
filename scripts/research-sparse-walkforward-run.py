#!/usr/bin/env python3
import importlib.util,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'scripts/research-sparse-walkforward-demand.py'
s=importlib.util.spec_from_file_location('sparse_core',p)
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

# Research-only capacity overrides. Defaults preserve the original sparse model.
m.MAX_RULES=int(os.environ.get('SPARSE_MAX_RULES',str(m.MAX_RULES)))
m.MAX_PER_BET=int(os.environ.get('SPARSE_MAX_PER_BET',str(m.MAX_PER_BET)))

_orig_q=m.quarter
_orig_select=m.select_rules

def quarter(date):
    if '2016-07-01' <= date < m.EVAL_START:
        return '2016Q3-warmup'
    return _orig_q(date)

def select_rules(stats,year_stats,cutoff):
    if cutoff < m.EVAL_START:
        return []
    return _orig_select(stats,year_stats,cutoff)

m.quarter=quarter
m.select_rules=select_rules
m.main()
