#!/usr/bin/env python3
"""Research-only: counterfactual marginal cash portfolio allocation.
Learn direct historical yen payout by market, popularity and odds structure;
then choose two DISTINCT markets by incremental historical portfolio utility.
Final odds are not T-15. Payout unit must be audited before yen ROI.
"""
import json
from pathlib import Path
from collections import defaultdict,Counter
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
CUT=(0,10,55,100,190,310,1030)
MARKETS=('win','wide','quinella','exacta','trio','trifecta')
def main():
 with np.load(ROOT/'analysis-results/jra-decade-sixmarket-top10-cash-v3.npz') as z:
  payouts=z['payout']
  if payouts.ndim!=2 or payouts.shape[1]!=1030 or not np.issubdtype(payouts.dtype,np.integer):
   raise RuntimeError('PAYOUT_CACHE_NOT_INT_YEN_PER_100YEN_TICKET')
  if np.any(payouts<0) or not np.any(payouts>=100):
   raise RuntimeError('PAYOUT_CACHE_INVALID_CASH_YEN_VALUES')
  # Source parse_payments() decodes the settled CSV payment integers into
  # yen per JRA 100-yen ticket. No final odds conversion or scaling applied.
  cash=payouts.astype(np.float64)
  rank=z['rankMin'].astype(np.int16)
  gap=z['rankGap'].astype(np.int16)
  odds=z['oddsGeom'].astype(np.int16)
  fav=z['favOdds'].astype(np.int16)
 races=json.loads((ROOT/'analysis-results/jra-decade-sixmarket-top10-races-v3.json').read_text())['races']
 years=np.array([int(r['month'][:4]) for r in races])
 results={}
 for year in (2023,2024,2025,2026):
  train=np.flatnonzero((years>=2015)&(years<year))
  test=np.flatnonzero(years==year)
  if not len(test):continue
  # Distinct from pairwise tournament and neighbour quantile: direct cash
  # conditional main-effect + regime-interaction uplift, trained on earlier
  # races, followed by a portfolio-level marginal diversification optimizer.
  scores=np.zeros((len(test),1030),dtype=np.float32)
  for m in range(6):
   lo,hi=CUT[m:m+2]
   y=cash[train,lo:hi]
   prior=float(y.mean())
   # Two deliberately limited monetary signals; no exhaustive pattern mining.
   for weight,a,b,bins in ((.55,rank,odds,90),(.45,gap,fav,55)):
    code=(a[:,lo:hi]*10+b[:,lo:hi]).astype(np.int32)
    x=code[train].ravel()
    n=np.bincount(x,minlength=bins)
    sums=np.bincount(x,weights=y.ravel(),minlength=bins)
    # Empirical Bayes: shrink low-support cells toward market baseline.
    estimate=(sums+150*prior)/(n+150)
    scores[:,lo:hi]+=weight*estimate[code[test]]
  selected=[]
  for pos,i in enumerate(test):
   top=[]
   for m in range(6):
    lo,hi=CUT[m:m+2]
    indices=np.argsort(scores[pos,lo:hi])[-3:][::-1]+lo
    top.extend((float(scores[pos,k]),m,int(k)) for k in indices)
   # Marginal utility of second ticket is evaluated on SAME historical races.
   # No outcome from evaluation year enters selection.
   best=None
   for a in top:
    for b in top:
     if a[1]>=b[1]:continue
     va=cash[train,a[2]];vb=cash[train,b[2]]
     # Profit objective penalizes co-loss and extreme single-win dependence.
     combined=(va+vb)/2
     downside=np.mean(np.minimum(combined,100))
     covloss=np.mean((va==0)&(vb==0))
     robust=(combined.sum()-combined.max())/len(combined)
     utility=.55*(a[0]+b[0])/2+.25*robust+.20*downside-30*covloss
     item=(utility,a[1],b[1],a[2],b[2])
     if best is None or item[0]>best[0]:best=item
   r=races[int(i)]
   selected.append((r.get('day',r['month']+'-'+r['id'][:10]),r.get('venue',r['id'][4:6]),int(i),best))
  groups=defaultdict(list)
  for day,venue,i,pair in selected:groups[(day,venue)].append((i,pair))
  chosen=[(i,p) for rows in groups.values() for i,p in sorted(rows,key=lambda v:-v[1][0])[:5]]
  # A payout entry is the actual yen returned on a 100-yen ticket. Both
  # legs are 100 yen, hence exactly 200 yen wagered on each chosen race.
  # The fixed ticket template index 0 is the favourite WIN; index 10 is the
  # top-two WIDE: useful no-model benchmark on identical selected race days.
  paid_ticket_yen=[int(cash[i,k]) for i,p in chosen for k in p[3:5]]
  paid_race_yen=[int(cash[i,p[3]]+cash[i,p[4]]) for i,p in chosen]
  baseline_paid_race_yen=[int(cash[i,0]+cash[i,10]) for i,_ in chosen]
  if not chosen or len(paid_ticket_yen)!=2*len(chosen):
   raise RuntimeError('NO_SELECTED_CASH_TICKETS')
  if any(p[1]==p[2] for _,p in chosen):
   raise RuntimeError('NON_DISTINCT_BET_MARKETS')
  cash_yen=int(sum(paid_ticket_yen))
  stake_yen=200*len(chosen)
  largest_ticket_yen=int(max(paid_ticket_yen,default=0))
  largest_race_yen=int(max(paid_race_yen,default=0))
  baseline_cash_yen=int(sum(baseline_paid_race_yen))
  baseline_largest_race_yen=int(max(baseline_paid_race_yen,default=0))
  def roi(paid):
   return round(100*paid/stake_yen,4)
  results[str(year)]={
   'trainYears':[int(years[train].min()),int(years[train].max())],
   'evaluationYear':year,'candidateRaces':len(test),'selectedRaces':len(chosen),
   'paidTickets':int(sum(1 for x in paid_ticket_yen if x>0)),
   'paidRaces':int(sum(1 for x in paid_race_yen if x>0)),
   'marketTicketCounts':dict(Counter(MARKETS[m] for _,p in chosen for m in p[1:3])),
   'stakeYen':stake_yen,'payoutYen':cash_yen,
   'profitYen':cash_yen-stake_yen,'cashRoiPct':roi(cash_yen),
   'maxTicketPayoutYen':largest_ticket_yen,
   'minusMaxTicketRoiPct':roi(cash_yen-largest_ticket_yen),
   'maxRacePayoutYen':largest_race_yen,
   'minusMaxRaceRoiPct':roi(cash_yen-largest_race_yen),
   'cashBaseline':'favorite win + two-favorites wide, same race selection',
   'baselinePayoutYen':baseline_cash_yen,
   'baselineRoiPct':roi(baseline_cash_yen),
   'baselineMinusMaxRaceRoiPct':roi(baseline_cash_yen-baseline_largest_race_yen),
   'sourceCashUnit':'settled third-party CSV payout integer yen per 100-yen stake',
   'sourceUnitInterpretationChecked':True,
   'independentlyReconciledWithOfficialJRA':False,
   'officialT15':False,
   'previouslyInspected':year>=2025,
   'passesCashRoi200':bool(len(chosen)>=100 and
      cash_yen>=2*stake_yen and
      cash_yen-largest_race_yen>=2*stake_yen)
  }
  print('MARGINAL_PORTFOLIO',json.dumps(results[str(year)]),flush=True)
 out=ROOT/'analysis-results/nov2026-cash-marginal-portfolio.json'
 out.parent.mkdir(exist_ok=True)
 out.write_text(json.dumps({'algorithm':'shrunken conditional monetary interactions plus same-race marginal cash portfolio','adopted':False,'payoutUnitAudit':'third-party CSV integer interpreted as yen per JRA 100-yen ticket; official JRA reconciliation and T-15 snapshots still missing','results':results},indent=2)+'\n')
if __name__=='__main__':main()
