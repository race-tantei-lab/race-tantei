#!/usr/bin/env python3
"""Research-only: market-conditional CASH uplift and portfolio downside co-loss.
Historical settled results, NOT official T-15 six-market odds.
"""
from collections import defaultdict,Counter
from pathlib import Path
import json
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
CUT=[0,10,55,100,190,310,1030]
FEATURES=('rankMin','oddsGeom','favOdds','fieldSize')
def cash_unit(payout):
    # Never silently infer money units from data: fail closed on ambiguity.
    # The pinned cache's payout unit must be independently audited.
    return payout

def run():
    with np.load(ROOT/'analysis-results/jra-decade-sixmarket-top10-cash-v3.npz') as raw:
        z={k:raw[k].astype(np.int32) for k in FEATURES}
        paid=raw['payout'].astype(np.float64)
    races=json.loads((ROOT/'analysis-results/jra-decade-sixmarket-top10-races-v3.json').read_text())['races']
    years=np.array([int(r['month'][:4]) for r in races])
    out={}
    for year in (2023,2024,2025,2026):
        tr=np.flatnonzero((years>=2015)&(years<year))
        te=np.flatnonzero(years==year)
        if not len(tr) or not len(te): continue
        # New hypothesis: historical cash uplift is meaningful only against
        # the *same race regime's* market opportunity cost; then two markets
        # must be selected by their joint negative cash residuals.
        market_scores=[];ticket_ids=[];historical_residuals=[]
        for m in range(6):
            lo,hi=CUT[m:m+2]
            y=paid[tr,lo:hi]
            # Train-only cap is applied to estimation, not settlement.
            capped=np.minimum(y,np.quantile(y,.997))
            regime=z['favOdds'][tr,lo]
            regime_test=z['favOdds'][te,lo]
            # Regime-specific historical baseline, computed by race.
            baseline=np.zeros(len(tr))
            for g in np.unique(regime):
                mask=regime==g
                baseline[mask]=capped[mask].mean()
            uplift=capped-baseline[:,None]
            score=np.zeros((len(te),hi-lo))
            # Cash residual interactions: rank x odds x favorite regime.
            key=(z['rankMin'][tr,lo:hi]*1000+
                 z['oddsGeom'][tr,lo:hi]*100+
                 z['favOdds'][tr,lo:hi])
            testkey=(z['rankMin'][te,lo:hi]*1000+
                     z['oddsGeom'][te,lo:hi]*100+
                     z['favOdds'][te,lo:hi])
            count=np.bincount(key.ravel(),minlength=11000)
            sums=np.bincount(key.ravel(),weights=uplift.ravel(),minlength=11000)
            # Empirical-Bayes shrinkage towards zero incremental cash.
            effects=sums/(count+250)
            score+=effects[testkey]
            # Historical cash benchmark in the same regime, not global.
            for g in np.unique(regime_test):
                mask=regime==g
                score[regime_test==g]+=capped[mask].mean() if mask.any() else capped.mean()
            best=np.argmax(score,axis=1)
            market_scores.append(score[np.arange(len(te)),best])
            ticket_ids.append(lo+best)
            # Ex ante cross-market hedge proxy from training-only payout
            # residuals for corresponding feature cells.
            residual=np.zeros((len(tr),))
            for g in np.unique(regime):
                mask=regime==g
                residual[mask]=np.mean(capped[mask].max(axis=1)-baseline[mask])
            historical_residuals.append(residual)
        market_scores=np.stack(market_scores,axis=1)
        ticket_ids=np.stack(ticket_ids,axis=1)
        # Co-loss estimated using past race-level market opportunity residuals;
        # pair choice is jointly optimized rather than independently top-two.
        hist=np.stack(historical_residuals,axis=1)
        risk=np.maximum(0,np.cov(hist,rowvar=False))
        scale=np.maximum(1,np.sqrt(np.outer(np.diag(risk),np.diag(risk))))
        risk=risk/scale
        groups=defaultdict(list)
        for j,i in enumerate(te):
            pairs=((float(market_scores[j,a]+market_scores[j,b]-
                    0.25*risk[a,b]*max(1,abs(market_scores[j,a]+market_scores[j,b]))),
                    a,b) for a in range(6) for b in range(a+1,6))
            utility,a,b=max(pairs,key=lambda x:(x[0],-x[1],-x[2]))
            r=races[int(i)]
            groups[(r.get('venue',r['id'][4:6]),r.get('day',r['id'][:8]))].append(
                (utility,int(i),a,b,int(ticket_ids[j,a]),int(ticket_ids[j,b])))
        selected=[]
        for group in groups.values():
            group.sort(key=lambda x:(-x[0],races[x[1]]['id']))
            selected.extend(group[:5])
        # Raw payouts recorded separately until pinned-cache unit is verified.
        gross_units=np.array([paid[i,x]+paid[i,y] for _,i,a,b,x,y in selected])
        out[str(year)]={'trainingYears':[int(years[tr].min()),int(years[tr].max())],
            'evaluationYear':year,'candidateRaces':len(te),'selectedRaces':len(selected),
            'tickets':2*len(selected),'marketPairs':dict(Counter(
                f'{a}-{b}' for _,i,a,b,x,y in selected)),
            'stakeYen':200*len(selected),'rawPayoutUnits':float(gross_units.sum()),
            'maxSingleRaceRawPayoutUnits':float(gross_units.max()) if len(gross_units) else 0,
            'payoutYen':None,'roiPct':None,'minusMaxPayoutRoiPct':None,
            'unitAuditRequired':True,'previouslyInspected':year>=2025}
        print('CASH_JOINT_UPLIFT',json.dumps(out[str(year)]),flush=True)
    p=ROOT/'analysis-results/nov2026-cash-joint-uplift.json'
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps({'hypothesis':'regime-relative cash uplift plus cross-market historical co-loss', 'officialT15':False,'adopted':False,'results':out},indent=2)+'\n')
if __name__=='__main__':run()
