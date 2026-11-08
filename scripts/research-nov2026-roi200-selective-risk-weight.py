#!/usr/bin/env python3
"""ROI-FIRST shortlist + financial stake-concentration model.

Rule discovery: historical actual paid 2024-H1-2025 market return >200% after
largest paid ticket removal. Select only 1..8 useful individual cells in
2025H2, NOT every historical rule. Cash risk allocation is itself searched
to maximize the realized payout ROI: two distinct JRA ticket types, each
>=¥100, total exactly ¥2000, five races per venue-day. Frozen 2026 test.

Never use 2026 money to optimize selection; actual third-party JRA mirror
payout and FINAL WIN quotes do not establish official T-15 market prices.
"""
from __future__ import annotations
import json,time,sys
from itertools import product
from pathlib import Path
import importlib.util
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'analysis-results/nov2026-roi200-cash-concentration-shortlist.json'
STAKE_SPLITS=(100,200,400,600,800,1000,1200,1400,1600,1800,1900)
SHORTLISTS=(1,2,3,4,5,8)
PAIR_INDICES=(-1,)+tuple(range(15))

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:raise RuntimeError('NO_HISTORICAL_FINANCIAL_SOURCE')
    m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m
    spec.loader.exec_module(m)
    return m

def market_cash(rows,days,y,first_stake):
    n=len(rows);stake=n*2000
    second_stake=2000-first_stake
    a=np.asarray([int(y[z[3]]) for z in rows],dtype=np.int64)
    b=np.asarray([int(y[z[4]]) for z in rows],dtype=np.int64)
    p1=a*(first_stake//100)
    p2=b*(second_stake//100)
    total=p1+p2;ret=int(total.sum())
    bigticket=int(max(np.max(p1,initial=0),np.max(p2,initial=0)))
    bigrace=int(np.max(total,initial=0))
    hits=int(np.sum(total>0))
    pct=lambda x,den:round(100*x/den,5) if den else None
    return {'races':n,'venueDays':days,'allFiveRacesPerVenueDay':n==days*5,
     'stakeYen':stake,'returnsYen':ret,'profitYen':ret-stake,
     'cashRoiPct':pct(ret,stake),
     'minusLargestTicketRoiPct':pct(ret-bigticket,stake),
     'minusLargestRaceRoiPct':pct(ret-bigrace,stake),
     'hitRacePct':pct(hits,n),
     'robust200':bool(stake and n>=100 and n==5*days and
             hits/n>=.2 and ret-bigticket>=stake*2 and ret-bigrace>=stake*2)}

def main():
    if '--self-test' in sys.argv:
        y=np.asarray([0,500,200])
        rows=[(1.,'r','202507',1,2,0)]
        assert market_cash(rows,1,y,1000)['cashRoiPct']==350.
        assert market_cash(rows,1,y,1800)['cashRoiPct']==470.
        print('ROI200_FINANCIAL_SELECTIVE_STAKE_MATH_OK',flush=True)
        return
    start=time.monotonic()
    base=load('scripts/research-nov2026-roi200-first-pattern-search.py',
              'concentration_base_patterns')
    single=load('scripts/research-nov2026-profitable-individual-rule-subsets.py',
              'concentration_selected_rules')
    races,y,ids,types,cat=single.history_and_categories(base)
    candidates,discovery=single.find_bettable_profitable_single_conditions(
          base,races,y,ids,types,cat)
    if not candidates:
        raise RuntimeError('NO_ACTUAL_CASH_PROFITABLE_SHORTLIST')
    print('CONCENTRATION_ROI200_RULE_UNIVERSE',json.dumps({
        'candidateRules':len(candidates),'historicalProfitConditions':discovery,
        'stakeSplitPossibilities':list(STAKE_SPLITS),'twoMarketTypesAlways':True},
        ensure_ascii=False),flush=True)
    period=('202507','202601')
    best=None;tested=0;eligible=0
    for n,metric in product(SHORTLISTS,('robustMoneyScore','stabilityMoneyScore')):
        ordered=sorted(candidates,key=lambda r:-r[metric])[:n]
        scores=single.shortlist_score(races,types,cat,base,ordered,metric)
        opts=single.shortlist_top_market_predictions(
                         races,types,scores,period)
        for pair in PAIR_INDICES:
            rows,days=single.rows_for_period(races,opts,pair)
            for stake in STAKE_SPLITS:
                m=market_cash(rows,days,y,stake)
                tested+=1
                if m['hitRacePct']<20:continue
                eligible+=1
                key=(int(m['robust200']),m['minusLargestRaceRoiPct'],
                     m['minusLargestTicketRoiPct'],m['cashRoiPct'],m['races'])
                if best is None or key>best[0]:
                    best=(key,n,metric,pair,stake,m)
    if best is None:raise RuntimeError('NO_MIN20_HIT_FINANCIAL_STAKE_PORTFOLIO')
    _,n,metric,pair,stake,h2=best
    frozen=sorted(candidates,key=lambda r:-r[metric])[:n]
    forecast=single.shortlist_score(races,types,cat,base,frozen,metric)
    opts=single.shortlist_top_market_predictions(
                         races,types,forecast,('202601','202604'))
    rows,days=single.rows_for_period(races,opts,pair)
    h26=market_cash(rows,days,y,stake)
    print('CONCENTRATION_FINANCIAL_H2_SELECTION',json.dumps({
        'subsetRules':n,'historicalScore':metric,'marketPair':pair,
        'firstMarketStakeYen':stake,'secondMarketStakeYen':2000-stake,
        'searched':tested,'meets20PctHit':eligible,
        'actualCash':h2},ensure_ascii=False),flush=True)
    print('CONCENTRATION_FINANCIAL_2026_FROZEN',json.dumps(h26,ensure_ascii=False),flush=True)
    result={'algorithm':'discover robust historical ROI200 condition cells; select only N useful individual cells; optimize money exposure across two different markets',
        'historicalRuleCells':frozen,'numberRulesSelected':n,
        'riskStakeFirstYen':stake,'riskStakeSecondYen':2000-stake,
        'marketPair':pair,
        'monetaryModelCandidates':tested,'eligibleHistoricalWith20PctHit':eligible,
        'ruleFinancialDiscovery':discovery,'2025H2MonetarySelection':h2,
        '2026JanMarFrozenMonetaryEvaluation':h26,
        'passesBothRealCashRobust200':bool(h2['robust200'] and h26['robust200']),
        'archiveActualMoneyIsThirdPartyUnreconciled':True,
        'quotedHistoricalOddsAreNotT15SixMarketOdds':True,
        '2026PreviouslyStudiedInOtherResearch':True,
        'productionModified':False,'adopted':False,
        'runtimeSeconds':round(time.monotonic()-start,2)}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('CONCENTRATION_REAL_CASH_RESULT_WRITTEN',str(OUT),flush=True)
if __name__=='__main__':main()
