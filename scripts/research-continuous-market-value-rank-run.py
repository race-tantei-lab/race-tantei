#!/usr/bin/env python3
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'scripts/research-evaluate-continuous-market-value.py'
spec=importlib.util.spec_from_file_location('market_base',BASE)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

_original_candidate_rows=mod.cmod.candidate_rows
_original_candidate_keys=mod.smod.candidate_keys


def candidate_rows_with_relative_rank(state,bundle):
    rows=_original_candidate_rows(state,bundle)
    rank_by_horse={}
    for t in rows:
        if t.get('bt')==0 and len(t.get('horses') or [])==1:
            horse=int(t['horses'][0])
            if horse not in rank_by_horse:
                rank_by_horse[horse]=len(rank_by_horse)+1
    out=[]
    for t in rows:
        ranks=tuple(rank_by_horse[int(h)] for h in t.get('horses',[]) if int(h) in rank_by_horse)
        x=dict(t);vals=dict(t.get('vals') or {})
        if ranks:
            vals['rankPattern']=ranks
            vals['rankSum']=sum(ranks)
            vals['bestRank']=min(ranks)
            vals['worstRank']=max(ranks)
        x['vals']=vals;out.append(x)
    return out


def candidate_keys_with_relative_rank(bt,vals):
    yield from _original_candidate_keys(bt,vals)
    pattern=vals.get('rankPattern')
    if pattern:
        pattern=tuple(pattern)
        yield (bt,('rankPattern',),(pattern,))
        yield (bt,('rankSum',),(int(vals['rankSum']),))
        yield (bt,('bestRank',),(int(vals['bestRank']),))
        yield (bt,('worstRank',),(int(vals['worstRank']),))


mod.cmod.candidate_rows=candidate_rows_with_relative_rank
mod.smod.candidate_keys=candidate_keys_with_relative_rank
mod.main()
