#!/usr/bin/env python3
"""Research-only rolling-quarter cash-pair portfolio; no official T-15 claim."""
import csv,gzip,importlib.util,json,sys
from pathlib import Path
from collections import defaultdict
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
BOUNDS=((0,7),(7,28),(28,49),(49,91),(91,126),(126,336))
def score(p,stake):
    if not len(p):return -1
    return (float(p.sum())-float(p.max()))/stake
def settle(rows):
    stake=sum(x['stakeYen'] for x in rows); paid=sum(x['paidYen'] for x in rows)
    return dict(races=len(rows),stakeYen=stake,paidYen=paid,hitRaces=sum(x['paidYen']>0 for x in rows),roiPct=round(100*paid/stake,4) if stake else None,minusMaxRaceRoiPct=round(100*(paid-max((x['paidYen'] for x in rows),default=0))/stake,4) if stake else None)
def run(races,cash,year,quarter,fields):
    money=cash.reshape(len(races),336)
    venue=np.array([str(r['venue']) for r in races])
    race_no=np.array([int(r['raceNo']) for r in races])
    day=np.array([str(r['day']) for r in races])
    band=np.where(fields<=9,0,np.where(fields<=13,1,2))
    stage=np.where(race_no<=4,0,np.where(race_no<=8,1,2))
    # All predictors are race-card data known before results.
    keys=[(venue[i],int(quarter[i]),int(band[i]),int(stage[i])) for i in range(len(races))]
    result=[];coverage={}
    for target in range(2023,2027):
      for q in range(1,5):
        test=np.flatnonzero((year==target)&(quarter==q))
        if not len(test):continue
        train=np.flatnonzero(((year<target)|((year==target)&(quarter<q)))&(year>=target-6))
        if len(train)<100:continue
        # Discover payout-rich and frequent-paying tickets in prior quarters,
        # then optimize their pair and stake allocation as one cash portfolio.
        # No evaluation-quarter payout or regime occurrence enters training.
        v=money[train]
        hits=np.count_nonzero(v,axis=0); robust=v.sum(axis=0)-v.max(axis=0)
        candidates=[]
        for lo,hi in BOUNDS:
          top_hit=sorted(range(lo,hi),key=lambda j:(hits[j],robust[j]),reverse=True)[:3]
          top_cash=sorted(range(lo,hi),key=lambda j:(robust[j],hits[j]),reverse=True)[:4]
          candidates.append(list(dict.fromkeys(top_hit+top_cash)))
        pairs=[(a,b) for k,aa in enumerate(candidates) for bb in candidates[k+1:] for a in aa for b in bb]
        # Portfolio selection is on the combined actual cash, not cell ROI thresholds.
        # Explore allocations 100/100, 100/200, 200/100 (all legal 100-yen units).
        allocations=((100,100),(100,200),(200,100))
        def optimize(ix):
          if len(ix)<20:return None
          z=money[np.asarray(ix,dtype=int)]
          best=None
          for a,b in pairs:
            for sa,sb in allocations:
              p=(z[:,a]*sa+z[:,b]*sb)//100
              objective=score(p,len(ix)*(sa+sb))
              # Prioritize combined robust yen ROI, tie-break by paying races.
              candidate=(objective,int(np.count_nonzero(p)),a,b,sa,sb)
              if best is None or candidate>best:best=candidate
          return best
        # Hierarchical shrinkage: only train-observed regimes; fallback to
        # venue-quarter or global when the specific regime is sparse.
        global_best=optimize(train)
        venue_ix=defaultdict(list);regime_ix=defaultdict(list)
        for i in train:
          i=int(i);venue_ix[(venue[i],int(quarter[i]))].append(i);regime_ix[keys[i]].append(i)
        venue_best={k:optimize(ix) for k,ix in venue_ix.items() if len(ix)>=45}
        regime_best={k:optimize(ix) for k,ix in regime_ix.items() if len(ix)>=60}
        days=defaultdict(list);unseen=0
        for i in test:
          i=int(i);key=keys[i]
          policy=regime_best.get(key) or venue_best.get((venue[i],int(quarter[i]))) or global_best
          if key not in regime_best:unseen+=1
          _,_,a,b,sa,sb=policy
          # Priority is learned from historical payout, never current results.
          row=dict(raceId=str(races[i]['id']),day=day[i],venue=venue[i],year=target,quarter=q,marketA=next(k for k,(lo,hi) in enumerate(BOUNDS) if lo<=a<hi),marketB=next(k for k,(lo,hi) in enumerate(BOUNDS) if lo<=b<hi),ticketA=a,ticketB=b,stakeA=sa,stakeB=sb,stakeYen=sa+sb,paidYen=int((money[i,a]*sa+money[i,b]*sb)//100),priority=policy[0])
          days[(day[i],venue[i])].append(row)
        counts=defaultdict(int)
        for rows in days.values():
          rows.sort(key=lambda x:(-x['priority'],x['raceId']))
          selected=rows[:5];result.extend(selected);counts[len(selected)]+=1
        coverage[f'{target}Q{q}']=dict(observedVenueDays=len(days),selected5=counts[5],selected3to5=sum(v for k,v in counts.items() if 3<=k<=5),lessThan3=sum(v for k,v in counts.items() if k<3),fallbackRegimeRaces=unseen,trainingRaces=len(train),testRaces=len(test))
    return result,coverage
def main():
    if '--self-test' in sys.argv:
      assert abs(score(np.array([500,100]),400)-0.25)<1e-9
      assert settle([dict(stakeYen=200,paidYen=500),dict(stakeYen=200,paidYen=100)])['minusMaxRaceRoiPct']==25
      print('ROLLING_CASH_PAIR_SELF_TEST_OK');return
    src=ROOT/'scripts/research-nov2026-seasonal-ensemble-cash-first.py'
    spec=importlib.util.spec_from_file_location('cashsrc',src)
    m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
    races,cash,cat,widths,types,rid,year,quarter,joint=m.obtain_rows()
    if len(cash)!=336*len(races) or np.any(cash<0):raise RuntimeError('INVALID_CASH_DATA')
    fields=cat['fieldSize'].reshape(len(races),336)[:,0].astype(int)
    bets,coverage=run(races,cash,year,quarter,fields)
    if not bets:raise RuntimeError('NO_BETS')
    if any(b['marketA']==b['marketB'] for b in bets):raise RuntimeError('SAME_MARKET')
    if len({(b['raceId'],b['day'],b['venue']) for b in bets})!=len(bets):raise RuntimeError('DUPLICATE_RACE')
    report=dict(researchOnly=True,adoptable=False,officialT15Verified=False,officialJraPayoutReconciled=False,source='third_party_unreconciled',method='rolling_quarter_cash_pair_allocation',knownPriorExposure2025And2026=True,combined=settle(bets),years={str(y):settle([b for b in bets if b['year']==y]) for y in range(2023,2027)},quarters={f'{y}Q{q}':settle([b for b in bets if b['year']==y and b['quarter']==q]) for y in range(2023,2027) for q in range(1,5)},coverage=coverage)
    out=ROOT/'analysis-results';out.mkdir(exist_ok=True)
    (out/'nov2026-rolling-cash-pair.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    with gzip.open(out/'nov2026-rolling-cash-pair-bets.csv.gz','wt',newline='') as f:
      w=csv.DictWriter(f,fieldnames=list(bets[0]));w.writeheader();w.writerows(bets)
    print('ROLLING_CASH_PAIR_RESULT',json.dumps(report,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
