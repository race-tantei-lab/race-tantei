#!/usr/bin/env python3
import argparse,collections,itertools,json,math
from pathlib import Path

BET_SPECS={
 'win':('単勝',1,True),'umaren':('馬連',2,False),'wide':('ワイド',2,False),
 'umatan':('馬単',2,True),'trio':('3連複',3,False),'trifecta':('3連単',3,True),
}
COURSES={'light':2000,'standard':5000,'premium':10000}
ODDS_EDGES=[2,3,5,7,10,15,20,30,50,75,100,150,300,500,800,1200,2000]
ODDS_MID=[1.4,2.45,3.9,5.9,8.4,12.2,17.3,24.5,38.7,61.2,86.6,122.5,212.1,387.3,632.5,979.8,1549.2,2500.0]
TEMPS=[0.35,0.5,0.7,1.0,1.4,2.0,3.0]
ALPHAS=[0.25,0.5,0.75,1.0]
YEARS=list(range(2016,2027))


def norm_combo(bt,horses):
    if bt in ('umaren','wide','trio'):horses=tuple(sorted(horses))
    return '-'.join(str(x) for x in horses)

def odds_value(v):
    if isinstance(v,list):
        vals=[float(x) for x in v if x is not None];return sum(vals)/len(vals) if vals else None
    return float(v) if v is not None else None

def bsearch(edges,x):
    i=0
    while i<len(edges) and x>=edges[i]:i+=1
    return i

def allocate(odds_list,budget):
    U=budget//100;n=len(odds_list);cap=max(1,int(math.floor(U*.35+1e-12)))
    if n<3 or n>10 or n*cap<U:raise RuntimeError(f'INVALID_ALLOCATION:{n}:{U}:{cap}')
    bins=[bsearch(ODDS_EDGES,o) for o in odds_list];units=[1]*n;rem=U-n
    weights=[min(1.0,(100.0/ODDS_MID[b])**1.5) for b in bins];tw=sum(weights);targets=[U*w/tw for w in weights]
    while rem>0:
        elig=[i for i in range(n) if units[i]<cap]
        if not elig:raise RuntimeError('ALLOCATION_FAILED')
        elig.sort(key=lambda i:(-(targets[i]-units[i]),-weights[i],ODDS_MID[bins[i]],i));units[elig[0]]+=1;rem-=1
    return units

def zscores(rows,key):
    vals=[float(r[key]) for r in rows];m=sum(vals)/len(vals);v=sum((x-m)**2 for x in vals)/max(1,len(vals));s=math.sqrt(v)
    if s<1e-12:return {int(r['horseNo']):0.0 for r in rows}
    return {int(r['horseNo']):(float(r[key])-m)/s for r in rows}

def normalize(raw):
    s=sum(raw.values());return {k:v/s for k,v in raw.items()} if s>0 else None

def race_inputs(pred_rows,official):
    winraw=official.get('win',{});win={int(h):odds_value(v) for h,v in winraw.items() if odds_value(v) is not None and odds_value(v)>1.0}
    active=[r for r in pred_rows if int(r['horseNo']) in win]
    if len(active)<3:return None
    za=zscores(active,'abilityScore')
    market=normalize({h:1.0/max(1.01,o) for h,o in win.items() if h in za})
    winner=next((int(r['horseNo']) for r in active if int(r.get('finishPosition') or 0)==1),None)
    return {'active':active,'za':za,'market':market,'winner':winner}

def model_prob(inp,temp):
    mx=max(inp['za'].values());raw={h:math.exp(max(-20,min(20,(z-mx)/temp))) for h,z in inp['za'].items()};return normalize(raw)

def blended_prob(inp,temp,alpha):
    pm=model_prob(inp,temp);qm=inp['market'];raw={h:(max(1e-15,pm[h])**alpha)*(max(1e-15,qm[h])**(1-alpha)) for h in pm};return normalize(raw)

def calibrate(prior_races,mode):
    if not prior_races:
        return {'temp':1.0,'alpha':1.0 if mode=='ability' else 0.5,'nll':None,'calibrationRaces':0,'defaultUsed':True}
    best=None
    alphas=[1.0] if mode=='ability' else ALPHAS
    for temp in TEMPS:
        for alpha in alphas:
            loss=0.0;n=0
            for inp in prior_races:
                w=blended_prob(inp,temp,alpha);winner=inp['winner']
                if winner is None or winner not in w:continue
                loss-=math.log(max(1e-15,w[winner]));n+=1
            if not n:continue
            avg=loss/n;key=(avg,temp,-alpha)
            if best is None or key<best[0]:best=(key,{'temp':temp,'alpha':alpha,'nll':round(avg,8),'calibrationRaces':n,'defaultUsed':False})
    if best is None:raise RuntimeError('CALIBRATION_FAILED')
    return best[1]

def ordered2(w,a,b):return w[a]*w[b]/max(1e-15,1.0-w[a])
def ordered3(w,a,b,c):return w[a]*(w[b]/max(1e-15,1.0-w[a]))*(w[c]/max(1e-15,1.0-w[a]-w[b]))
def ticket_prob(bt,horses,w):
    if bt=='win':return w[horses[0]]
    if bt=='umatan':return ordered2(w,*horses)
    if bt=='umaren':
        a,b=horses;return ordered2(w,a,b)+ordered2(w,b,a)
    if bt=='trifecta':return ordered3(w,*horses)
    if bt=='trio':return sum(ordered3(w,*p) for p in itertools.permutations(horses,3))
    a,b=horses;out=0.0
    for c in w:
        if c in (a,b):continue
        out+=sum(ordered3(w,*p) for p in ((a,b,c),(a,c,b),(b,a,c),(b,c,a),(c,a,b),(c,b,a)))
    return out

def candidate_horses(w,market):
    leaders=[h for h,_ in sorted(w.items(),key=lambda kv:(-kv[1],kv[0]))[:6]]
    edge=sorted(w,key=lambda h:(-(w[h]/max(1e-15,market[h])),h))[:2]
    out=[]
    for h in leaders+edge:
        if h not in out:out.append(h)
    return out[:8]

def build_tickets(w,market,official):
    pool=candidate_horses(w,market);tickets=[]
    for bt,(jp,k,ordered) in BET_SPECS.items():
        if len(pool)<k:continue
        seq=itertools.permutations(pool,k) if ordered else itertools.combinations(pool,k)
        om=official.get(bt,{})
        for hs in seq:
            combo=norm_combo(bt,hs);ov=odds_value(om.get(combo))
            if ov is None or ov<=1.0:continue
            p=ticket_prob(bt,hs,w);tickets.append({'bt':bt,'betType':jp,'horses':list(hs),'combo':combo,'odds':ov,'prob':p,'ev':p*ov})
    tickets.sort(key=lambda t:(-t['ev'],-t['prob'],t['odds'],t['bt'],t['combo']))
    if len(tickets)<3:return None
    chosen=[tickets[0]];types={tickets[0]['bt']}
    second=next((t for t in tickets[1:] if t['bt'] not in types),None)
    if second is None:return None
    chosen.append(second);used={(t['bt'],t['combo']) for t in chosen}
    third=next((t for t in tickets if (t['bt'],t['combo']) not in used),None)
    if third is None:return None
    chosen.append(third);chosen.sort(key=lambda t:(-t['ev'],-t['prob'],t['bt'],t['combo']))
    return chosen

def payout_index(bundle):
    out={}
    for p in bundle.get('payouts',[]):
        bt=str(p.get('betType') or '');combo=str(p.get('combination') or '');pay=p.get('payoutYen')
        if bt and combo and pay is not None:out[(bt,combo)]=int(pay)
    return out

def robust(rows):
    total_stake=sum(r['stakeYen'] for r in rows);total_return=sum(r['returnYen'] for r in rows);ordered=sorted(rows,key=lambda r:(-r['returnYen'],r['raceId']))
    def cut(n):
        n=min(n,len(ordered));rm=ordered[:n];stake=total_stake-sum(r['stakeYen'] for r in rm);ret=total_return-sum(r['returnYen'] for r in rm)
        return round(100*ret/stake,4) if stake else None
    n1=max(1,math.ceil(len(rows)*.01));top50=cut(50)
    return {'races':len(rows),'stakeYen':total_stake,'returnYen':total_return,'roiPct':round(100*total_return/total_stake,4),'top50ExcludedRoiPct':top50,'top100ExcludedRoiPct':cut(100),'top1PctExcludedRaceCount':n1,'top1PctExcludedRoiPct':cut(n1),'top50ReturnSharePct':round(100*sum(r['returnYen'] for r in ordered[:50])/total_return,4) if total_return else 0.0,'hardGateTop50AtLeast200':bool(top50 is not None and top50>=200.0)}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--predictions-dir',required=True);ap.add_argument('--odds-dir',required=True);ap.add_argument('--history',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    preds=collections.defaultdict(list)
    for p in sorted(Path(a.predictions_dir).glob('runner-ranker-20*.jsonl')):
        for line in p.read_text(encoding='utf-8').splitlines():
            if line.strip():r=json.loads(line);preds[str(r['raceId'])].append(r)
    odds={}
    for p in sorted(Path(a.odds_dir).glob('research-continuous-market-odds-20*.jsonl')):
        for line in p.read_text(encoding='utf-8').splitlines():
            if line.strip():r=json.loads(line);rid=str(r['raceId']);odds[rid]=r
    hist={}
    with Path(a.history).open(encoding='utf-8') as fh:
        for line in fh:
            if line.strip():b=json.loads(line);rid=str(b['race']['raceId']);hist[rid]=b
    if len(preds)!=14410 or len(odds)<14410:raise RuntimeError(f'INPUT_COUNT_INVALID:{len(preds)}:{len(odds)}')
    selected=sorted(preds,key=lambda rid:(str(odds[rid]['raceDate']),str(odds[rid]['venue']),int(odds[rid]['raceNo'])))
    inputs={};by_year=collections.defaultdict(list)
    for rid in selected:
        inp=race_inputs(preds[rid],odds[rid]['officialOdds'])
        if inp is None or inp['winner'] is None:raise RuntimeError(f'RACE_INPUT_INVALID:{rid}')
        inputs[rid]=inp;by_year[int(str(odds[rid]['raceDate'])[:4])].append(rid)
    calibration={'ability':{},'blend':{}}
    for mode in ('ability','blend'):
        prior=[]
        for y in YEARS:
            calibration[mode][str(y)]=calibrate([inputs[r] for r in prior],mode)
            prior.extend(by_year.get(y,[]))
    results={mode:collections.defaultdict(list) for mode in ('ability','blend')};errors=[]
    for idx,rid in enumerate(selected,1):
        y=str(odds[rid]['raceDate'])[:4];o=odds[rid];inp=inputs[rid];pays=payout_index(hist[rid])
        for mode in ('ability','blend'):
            cal=calibration[mode][y];w=blended_prob(inp,cal['temp'],cal['alpha']);chosen=build_tickets(w,inp['market'],o['officialOdds'])
            if not chosen:errors.append({'raceId':rid,'mode':mode,'reason':'TICKET_SELECTION_FAILED'});continue
            for course,budget in COURSES.items():
                units=allocate([t['odds'] for t in chosen],budget);ret=sum(u*pays.get((t['betType'],t['combo']),0) for t,u in zip(chosen,units))
                results[mode][course].append({'raceId':rid,'raceDate':o['raceDate'],'stakeYen':budget,'returnYen':ret})
        if idx%2000==0:print(json.dumps({'processed':idx,'errors':len(errors)},ensure_ascii=False),flush=True)
    if errors:raise RuntimeError(f'EVALUATION_ERRORS:{len(errors)}:{errors[:5]}')
    summary={'purpose':'research_only_temporally_calibrated_runner_ml_market','selectedRaces':14410,'historicalFinalOddsUsed':True,'prestartTimingValidationPerformed':False,'targetYearRoiUsedForCalibration':False,'targetRaceResultUsedForPrediction':False,'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False,'completionHardGate':{'allCoursesTop50ExcludedRoiPctAtLeast':200.0,'top50ExcludedRequired':True},'calibration':calibration,'models':{}}
    for mode in ('ability','blend'):
        m={'courses':{},'byYear':{},'byPeriod':{}}
        for course in COURSES:m['courses'][course]=robust(results[mode][course])
        for y in YEARS:m['byYear'][str(y)]={c:robust([r for r in results[mode][c] if r['raceDate'].startswith(str(y))]) for c in COURSES}
        periods={'2016-2018':('2016','2018'),'2019-2021':('2019','2021'),'2022-2024':('2022','2024'),'2025-2026':('2025','2026')}
        for name,(lo,hi) in periods.items():m['byPeriod'][name]={c:robust([r for r in results[mode][c] if lo<=r['raceDate'][:4]<=hi]) for c in COURSES}
        m['passesCompletionHardGate']=all(m['courses'][c]['hardGateTop50AtLeast200'] for c in COURSES);summary['models'][mode]=m
    Path(a.out).parent.mkdir(parents=True,exist_ok=True);Path(a.out).write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({mode:{c:{'roi':summary['models'][mode]['courses'][c]['roiPct'],'top50':summary['models'][mode]['courses'][c]['top50ExcludedRoiPct']} for c in COURSES}|{'pass':summary['models'][mode]['passesCompletionHardGate']} for mode in summary['models']},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
