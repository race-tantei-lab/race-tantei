#!/usr/bin/env python3
import argparse,collections,importlib.util,itertools,json,math
from pathlib import Path
import numpy as np
from lightgbm import LGBMClassifier

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ticketbase',ROOT/'scripts'/'research-evaluate-runner-ml-market.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
COURSES=base.COURSES
FEATURES=['logOdds','invOdds','abilityProb','marketPlProb','abilityVsMarketLogRatio','scoreGapMean','abilityRankSum','marketRankSum','popularitySum','fieldSize','topAbilityCount','maxAbilityRank','maxMarketRank']

def softmax(rows,key):
    vals={int(r['horseNo']):float(r[key]) for r in rows};mx=max(vals.values());e={h:math.exp(max(-50,min(50,v-mx))) for h,v in vals.items()};s=sum(e.values());return {h:v/s for h,v in e.items()}
def market_win(official):
    raw=official.get('win',{});q={int(h):1.0/max(1.01,base.odds_value(v)) for h,v in raw.items() if base.odds_value(v) is not None};s=sum(q.values());return {h:v/s for h,v in q.items()} if s else {}
def ranks(rows,key):return {int(r['horseNo']):i for i,r in enumerate(sorted(rows,key=lambda r:(-float(r[key]),int(r['horseNo']))),1)}
def popmap(rows):
    f=max(1,len(rows));return {int(r['horseNo']):max(1,int(r.get('marketPopularity') or f+1)) for r in rows}
def pool(rows):
    a=sorted(rows,key=lambda r:(-float(r['abilityScore']),int(r['horseNo'])));m=sorted(rows,key=lambda r:(-float(r['marketScore']),int(r['horseNo'])));out=[]
    for r in a[:5]+m[:1]:
        h=int(r['horseNo'])
        if h not in out:out.append(h)
    return out

def candidates(rows,official,pays=None):
    aw=softmax(rows,'abilityScore');mw=market_win(official);hs=[h for h in pool(rows) if h in aw and h in mw]
    if len(hs)<3:return []
    ar=ranks(rows,'abilityScore');mr=ranks(rows,'marketScore');pm=popmap(rows);gap={int(r['horseNo']):float(r['abilityScore'])-float(r['marketScore']) for r in rows}
    out=[]
    for bt,(jp,k,ordered) in base.BET_SPECS.items():
        if len(hs)<k:continue
        seq=itertools.permutations(hs,k) if ordered else itertools.combinations(hs,k)
        market=official.get(bt,{})
        for combo_h in seq:
            combo=base.norm_combo(bt,combo_h);od=base.odds_value(market.get(combo))
            if od is None or od<=1.0:continue
            ap=base.ticket_prob(bt,combo_h,aw);mp=base.ticket_prob(bt,combo_h,mw)
            vals=[gap[h] for h in combo_h]
            x=[math.log(max(1.000001,od)),1.0/od,ap,mp,math.log(max(1e-12,ap)/max(1e-12,mp)),sum(vals)/len(vals),sum(ar[h] for h in combo_h),sum(mr[h] for h in combo_h),sum(pm[h] for h in combo_h),len(rows),sum(1 for h in combo_h if ar[h]<=3),max(ar[h] for h in combo_h),max(mr[h] for h in combo_h)]
            label=int(bool(pays is not None and pays.get((jp,combo),0)>0))
            out.append({'bt':bt,'betType':jp,'combo':combo,'odds':od,'abilityProb':ap,'features':x,'label':label})
    return out

def make_model():return LGBMClassifier(objective='binary',n_estimators=180,learning_rate=.035,num_leaves=19,min_child_samples=120,subsample=.85,colsample_bytree=.9,reg_alpha=.8,reg_lambda=5.0,random_state=20260811,n_jobs=-1,verbosity=-1)
def train_models(prior):
    models={};counts={}
    for bt,rows in prior.items():
        pos=sum(r['label'] for r in rows);neg=len(rows)-pos;counts[bt]={'rows':len(rows),'positive':pos,'negative':neg}
        if pos<50 or neg<500:continue
        X=np.asarray([r['features'] for r in rows],dtype=np.float32);y=np.asarray([r['label'] for r in rows],dtype=np.int8);m=make_model();m.fit(X,y);models[bt]=m
    return models,counts

def select(cands,models):
    scored=[]
    by=collections.defaultdict(list)
    for c in cands:by[c['bt']].append(c)
    for bt,rows in by.items():
        if bt in models:
            X=np.asarray([r['features'] for r in rows],dtype=np.float32);pred=models[bt].predict_proba(X)[:,1]
        else:pred=np.asarray([r['abilityProb'] for r in rows])
        for r,p in zip(rows,pred):
            scored.append({**r,'predHitProb':float(p),'score':float(p)*r['odds']})
    scored.sort(key=lambda r:(-r['score'],-r['predHitProb'],r['odds'],r['bt'],r['combo']))
    if len(scored)<3:return None
    chosen=[scored[0]];types={scored[0]['bt']};second=next((r for r in scored[1:] if r['bt'] not in types),None)
    if second is None:return None
    chosen.append(second);used={(r['bt'],r['combo']) for r in chosen};third=next((r for r in scored if (r['bt'],r['combo']) not in used),None)
    if third is None:return None
    chosen.append(third);chosen.sort(key=lambda r:(-r['score'],-r['predHitProb'],r['bt'],r['combo']))
    return chosen

def read_jsonl(p):
    with Path(p).open(encoding='utf-8') as f:
        for line in f:
            if line.strip():yield json.loads(line)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--predictions-dir',required=True);ap.add_argument('--odds-dir',required=True);ap.add_argument('--history',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    preds=collections.defaultdict(list)
    for p in sorted(Path(a.predictions_dir).glob('runner-ranker-20*.jsonl')):
        for r in read_jsonl(p):preds[str(r['raceId'])].append(r)
    odds={}
    for p in sorted(Path(a.odds_dir).glob('research-continuous-market-odds-20*.jsonl')):
        for r in read_jsonl(p):odds[str(r['raceId'])]=r
    hist={}
    for b in read_jsonl(a.history):hist[str(b['race']['raceId'])]=b
    if len(preds)!=14410 or len(odds)!=14410 or len(hist)!=14410:raise RuntimeError(f'INPUT_COUNTS:{len(preds)}:{len(odds)}:{len(hist)}')
    ids=sorted(preds,key=lambda rid:(odds[rid]['raceDate'],odds[rid]['venue'],int(odds[rid]['raceNo'])));byyear=collections.defaultdict(list)
    for rid in ids:byyear[odds[rid]['raceDate'][:4]].append(rid)
    prior=collections.defaultdict(list);race_rows=collections.defaultdict(list);training_diag={};errors=[]
    for y in sorted(byyear):
        models,counts=train_models(prior);training_diag[y]={'models':sorted(models),'priorCounts':counts}
        frozen=[]
        for rid in byyear[y]:
            c=candidates(preds[rid],odds[rid]['officialOdds']);chosen=select(c,models)
            if not chosen:errors.append({'raceId':rid,'reason':'TICKET_SELECTION_FAILED'});continue
            pays=base.payout_index(hist[rid]);frozen.append((rid,chosen,pays))
            for course,budget in COURSES.items():
                units=base.allocate([r['odds'] for r in chosen],budget);ret=sum(u*pays.get((r['betType'],r['combo']),0) for r,u in zip(chosen,units));race_rows[course].append({'raceId':rid,'raceDate':odds[rid]['raceDate'],'stakeYen':budget,'returnYen':ret})
        # Only after the entire evaluation year is frozen are its outcomes added to next years' training.
        for rid in byyear[y]:
            pays=base.payout_index(hist[rid])
            for c in candidates(preds[rid],odds[rid]['officialOdds'],pays):prior[c['bt']].append(c)
    if errors:raise RuntimeError(f'EVALUATION_ERRORS:{len(errors)}:{errors[:5]}')
    courses={c:base.robust(race_rows[c],b) for c,b in COURSES.items()};years=sorted(byyear)
    by_year={y:{c:base.robust([r for r in race_rows[c] if r['raceDate'].startswith(y)],b) for c,b in COURSES.items()} for y in years}
    periods={'2016-2018':('2016','2018'),'2019-2021':('2019','2021'),'2022-2024':('2022','2024'),'2025-2026':('2025','2026')}
    by_period={n:{c:base.robust([r for r in race_rows[c] if lo<=r['raceDate'][:4]<=hi],b) for c,b in COURSES.items()} for n,(lo,hi) in periods.items()}
    out={'purpose':'research_only_prior_year_ticket_hit_classifier','selectedRaces':14410,'trainingBoundary':'prior_years_only','targetYearResultsUsedForTicketModel':False,'targetYearRoiUsedForTuning':False,'trainingDiagnosticsByYear':training_diag,'courses':courses,'byYear':by_year,'byPeriod':by_period,'passesCompletionHardGate':all(courses[c]['top50ExcludedRoiPct']>=200 for c in COURSES),'completionHardGate':{'allCoursesTop50ExcludedRoiPctAtLeast':200.0},'historicalFinalOddsUsed':True,'prestartTimingValidationPerformed':False,'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False}
    Path(a.out).parent.mkdir(parents=True,exist_ok=True);Path(a.out).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'courses':{c:{'roi':v['roiPct'],'top50':v['top50ExcludedRoiPct'],'top100':v['top100ExcludedRoiPct'],'top1pct':v['top1PctExcludedRoiPct']} for c,v in courses.items()},'pass':out['passesCompletionHardGate'],'modelsByYear':{y:x['models'] for y,x in training_diag.items()}},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
