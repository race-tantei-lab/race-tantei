#!/usr/bin/env python3
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'scripts/research-evaluate-continuous-market-value.py'
spec=importlib.util.spec_from_file_location('market_base_norm',BASE)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

_original_prepare=mod.prepare_market_candidates


def prepare_with_market_implied_probability(rows,odds_row,key_stats,bet_stats):
    prepared=_original_prepare(rows,odds_row,key_stats,bet_stats)
    official=odds_row.get('officialOdds') or {}
    denominators={}
    for market,values in official.items():
        inv=0.0
        for value in (values or {}).values():
            odd=mod.midpoint(value)
            if odd is not None and odd>=1.0:
                inv+=1.0/odd
        denominators[market]=inv
    out=[]
    for t in prepared:
        den=denominators.get(t['market'],0.0)
        if den<=0:raise RuntimeError(f'MARKET_IMPLIED_DENOM_INVALID:{t["market"]}')
        q=(1.0/t['odds'])/den
        if q<=0:raise RuntimeError(f'MARKET_IMPLIED_PROB_INVALID:{t["market"]}:{t["combo"]}')
        x=dict(t);x['marketImpliedProb']=q;out.append(x)
    return out


def score_normalized(prepared,local_weight,risk_gamma):
    out=[]
    for t in prepared:
        p=(1.0-local_weight)*t['baseProb']+local_weight*t['localProb']
        raw_ev=p*t['odds']
        normalized_edge=p/t['marketImpliedProb']
        score=normalized_edge*((10.0/max(1.0,t['odds']))**risk_gamma)
        out.append({**t,'pHat':p,'ev':raw_ev,'normalizedEdge':normalized_edge,'marketScore':score})
    out.sort(key=lambda x:(-x['marketScore'],-x['normalizedEdge'],-x['ev'],x['odds'],x['bt'],x['combo']))
    return out


mod.prepare_market_candidates=prepare_with_market_implied_probability
mod.score_variant=score_normalized
mod.main()
