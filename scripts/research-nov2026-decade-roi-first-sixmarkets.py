#!/usr/bin/env python3
"""Actual-money ROI-FIRST pattern discovery from 2015 to 2026, ALL 6 JRA bet types.

Unlike prior two-year studies, the underlying third-party finished-race payout
mirror has pinned MONTHLY DATA BACK TO 2015, allowing 2015-2022 TRAIN,
2023 independent repeatability audit, 2024 policy selection, and untouched
2025 + 2026 Jan-Apr evaluations. The discovery objective is ACTUAL payout yen,
not horse win probability, log-loss, or classification accuracy.

Conjunction searches produce OPTIONAL subset rules. Only cells with historical
ROI>=200%, adequate paid-ticket support, robust max payout removal are
permitted; 2023 independent measured return determines stability. Rule scores
are historical cash-return strength, not predictions from a horse model.
All six wager types, up to six low-odds-priced horses, two *different* bet
types with ¥100+ each; 1-5 races/day/venue or full five.

No live deployment. Payouts are a third-party JRA settled-results mirror and
FINAL WIN odds, not official JRA T-15 SIX COMBINATION price snapshots.
"""
from __future__ import annotations
from collections import Counter,defaultdict
from itertools import combinations,permutations,product
from pathlib import Path
import csv,importlib.util,json,math,re,sys,time
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
FILES=ROOT/'external-jra-cash-decade'
OUT=ROOT/'analysis-results/nov2026-decade-ten-runner-roi200-loose-stability.json'
MARKETS=('単勝','ワイド','馬連','馬単','3連複','3連単')
TOP_N=10
COLS=('単勝払戻','ワイド払戻','馬連払戻','馬単払戻','三連複払戻','三連単払戻')
UNORDERED={1,2,4}
TARGET_YEAR_END=2026
CACHE=ROOT/'analysis-results/jra-decade-sixmarket-top10-cash-v3.npz'
RACE_CACHE=ROOT/'analysis-results/jra-decade-sixmarket-top10-races-v3.json'
SEED=20261108
COMBO_PER_MARKET=[10,45,45,90,120,720]
START_MARKET=np.cumsum([0]+COMBO_PER_MARKET).astype(int)
N=sum(COMBO_PER_MARKET)
assert N==1030
SINGLE_BINS={
 'rankMin':10,'rankMax':10,'rankSum':13,'rankGap':10,
 'rankFirst':10,'rankSecond':11,'favCount':4,'rankExact':1000,
 'oddsGeom':8,'oddsSpread':5,'horseAge':5,'draw':5,
 'horseWeight':5,'favOdds':5,'favGap':4,
 'venue':10,'fieldSize':4,'raceBand':3,'quarter':4,
}
SMALL=['rankMin','rankMax','rankSum','rankGap','rankFirst','rankSecond',
       'favCount','oddsGeom','oddsSpread','horseAge','draw',
       'horseWeight','favOdds','favGap','venue','fieldSize','raceBand','quarter']
PATTERNS=[(x,) for x in SMALL]+[
 ('rankExact',),('rankExact','favOdds'),('rankExact','fieldSize'),
 ('rankFirst','rankSecond'),('rankMin','rankMax'),('rankMin','oddsGeom'),
 ('rankMax','oddsGeom'),('rankSum','oddsGeom'),
 ('rankFirst','oddsGeom'),('rankGap','oddsGeom'),
 ('favCount','oddsGeom'),('rankMin','favOdds'),('rankMax','favOdds'),
 ('rankFirst','favOdds'),('rankSum','favOdds'),
 ('rankMin','venue'),('rankMax','venue'),('rankSum','venue'),
 ('rankFirst','venue'),('oddsGeom','venue'),
 ('oddsGeom','fieldSize'),('oddsGeom','raceBand'),
 ('oddsGeom','quarter'),('rankGap','venue'),
 ('rankFirst','quarter'),('rankSum','quarter'),
 ('rankFirst','fieldSize'),('rankMin','fieldSize'),
 ('rankMax','fieldSize'),('favCount','fieldSize'),
 ('oddsGeom','horseAge'),('rankFirst','horseAge'),
 ('rankMin','horseAge'),('rankMax','horseAge'),
 ('oddsGeom','draw'),('rankMin','draw'),('rankFirst','draw'),
 ('rankMin','horseWeight'),('oddsGeom','horseWeight'),
 ('horseAge','venue'),('draw','venue'),('fieldSize','venue'),
 ('raceBand','venue'),('quarter','venue'),
 ('favOdds','venue'),('favOdds','fieldSize'),
 ('favOdds','quarter'),('favOdds','oddsGeom'),
 ('favOdds','rankGap'),('favGap','rankGap'),
 ('favGap','rankMax'),('favGap','rankMin'),
 ('rankMin','rankMax','favOdds'),
 ('rankFirst','oddsGeom','favOdds'),
 ('rankFirst','oddsGeom','venue'),
 ('rankMax','oddsGeom','venue'),
 ('rankMin','rankMax','fieldSize'),
 ('rankSum','oddsGeom','fieldSize'),
 ('rankFirst','rankSecond','oddsGeom'),
 ('favCount','rankMax','favOdds'),
 ('oddsGeom','venue','quarter'),
 ('rankSum','venue','quarter'),
 ('rankMin','horseAge','fieldSize'),
 ('rankMax','draw','venue'),
 ('rankFirst','draw','quarter')
]
MIN_GROUP_SIZES=(60,150,350)
SELECTIONS=(1,3,8,20,50,100)
MARKET_PAIR_CHOICES=(-1,)+tuple(range(15))
MARKET_PAIRS=tuple(combinations(range(6),2))
STAKE_SPLITS=(100,400,1000,1600,1900)
NUMBER_RACES=(1,2,3,5)
MIN_YEARS=2

def mod(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:raise RuntimeError('NO_SHARED_PAID_JRA_SOURCE')
    x=importlib.util.module_from_spec(spec)
    sys.modules[name]=x
    spec.loader.exec_module(x)
    return x

def fixed_template():
    slots=[];mids=[]
    for m in range(6):
        if m==0:raw=[(i,) for i in range(TOP_N)]
        elif m in (1,2):raw=list(combinations(range(TOP_N),2))
        elif m==3:raw=list(permutations(range(TOP_N),2))
        elif m==4:raw=list(combinations(range(TOP_N),3))
        else:raw=list(permutations(range(TOP_N),3))
        slots.extend(raw);mids.extend([m]*len(raw))
    if len(slots)!=N:raise RuntimeError('WRONG_ALL_SIX_MARKET_COMBINATION_TEMPLATE')
    return slots,np.asarray(mids,dtype=np.int8)

def read_all_races(parse):
    files=sorted(FILES.glob('raceresults_*.csv'))
    if len(files)!=136:raise RuntimeError('MISSING_HISTORICAL_MONTHLY_SIX_MARKET_PAYOUT_CSVS:'+str(len(files)))
    by_race={};audit=Counter()
    for file in files:
        stamp=file.stem.split('_')[-1]
        if not re.fullmatch(r'20(1[5-9]|2[0-6])(0[1-9]|1[0-2])',stamp):
            raise RuntimeError('UNEXPECTED_PINNED_YEAR_FILE:'+file.name)
        if stamp[:4]=='2026' and stamp[4:] not in ('01','02','03','04'):continue
        with file.open(encoding='utf-8-sig',newline='') as f:
            for record in csv.DictReader(f):
                rid=str(record.get('race_id','')).strip()
                if not(re.fullmatch(r'\d{12}',rid) and rid[:4]==stamp[:4]):
                    audit['badRaceIds']+=1;continue
                key=stamp,rid
                r=by_race.get(key)
                if r is None:
                    try:
                        pays=[parse(record.get(col,''),m)
                              for col,m in zip(COLS,MARKETS)]
                    except (TypeError,ValueError):
                        audit['badSettledPayouts']+=1;continue
                    if any(not p for p in pays):
                        audit['missingSixActualCashMarkets']+=1;continue
                    r={'id':rid,'month':stamp,'day':stamp+'-'+rid[:10],
                       'venue':int(rid[4:6]),'raceNo':int(rid[-2:]),
                       'payout':pays,'horses':[]}
                    by_race[key]=r
                try:
                    no=int(record['馬番'])
                    odds=float(record['単勝オッズ'])
                    age_match=re.search(r'\d+',record.get('性齢',''))
                    age=int(age_match.group()) if age_match else 0
                    assign=float(record.get('斤量') or 0)
                    if not (1<=no<=18 and 1<=odds<=9999 and
                      math.isfinite(odds) and 0<=age<=18 and
                      0<=assign<=80):raise ValueError
                    r['horses'].append((no,odds,age,assign))
                except (ValueError,TypeError,KeyError):
                    audit['badRunnerOdds']+=1
    results=[]
    for r in by_race.values():
        if r['venue']<1 or r['venue']>10 or r['raceNo']<1 or r['raceNo']>12:
            audit['outsideJraCentralRaceRange']+=1;continue
        h=r['horses']
        if len(h)<TOP_N or len({x[0] for x in h})!=len(h):
            audit['tooFewOrDuplicatedHorseNo']+=1;continue
        h.sort(key=lambda x:(x[1],x[0]))
        results.append(r)
    results.sort(key=lambda r:(r['month'],r['id']))
    byyr=Counter(r['month'][:4] for r in results)
    for yr in range(2015,2026):
        if byyr[str(yr)]<1800:
            raise RuntimeError('HISTORIC_YEAR_TOO_FEW_SIX_MARKET_SETTLED_JRA_RACES:'+str(yr)+':'+str(byyr[str(yr)]))
    if byyr['2026']<400:raise RuntimeError('2026_EVALUATION_TOO_FEW_RACES')
    audit['racesByYear']=dict(sorted(byyr.items()))
    audit['count']=len(results)
    audit['sourceFiles']=len(files)
    print('DECADE_ALL_SIX_MARKET_ACTUAL_CASH_SOURCE',json.dumps(
               dict(audit),ensure_ascii=False),flush=True)
    return results

def full_features(races):
    n=len(races)
    slots,markets=fixed_template()
    indices=np.zeros((N,3),dtype=np.int8)
    mask=np.zeros((N,3),dtype=bool)
    for j,s in enumerate(slots):
        indices[j,:len(s)]=s;mask[j,:len(s)]=True
    span=mask.sum(axis=1).astype(float)
    constant={
      'rankMin':np.asarray([min(s) for s in slots],np.uint8),
      'rankMax':np.asarray([max(s) for s in slots],np.uint8),
      'rankSum':np.asarray([min(sum(s)//2,12) for s in slots],np.uint8),
      'rankGap':np.asarray([max(s)-min(s) for s in slots],np.uint8),
      'rankFirst':np.asarray([s[0] for s in slots],np.uint8),
      'rankSecond':np.asarray([s[1] if len(s)>1 else TOP_N for s in slots],np.uint8),
      'favCount':np.asarray([sum(k<=1 for k in s) for s in slots],np.uint8),
      'rankExact':np.asarray([s[0]*TOP_N*TOP_N+(s[1] if len(s)>1 else 0)*TOP_N+
                         (s[2] if len(s)>2 else 0) for s in slots],np.uint16),
    }
    categories={k:np.empty((n,N),dtype=(np.uint16 if k=='rankExact' else np.uint8))
                for k in SINGLE_BINS}
    paid=np.zeros((n,N),dtype=np.int32)
    odds_edges=[2.,3.5,5.5,8,12,20,40]
    for i,r in enumerate(races):
        horse=r['horses'][:TOP_N]
        nums=np.asarray([x[0] for x in horse],dtype=np.int16)
        odds=np.asarray([x[1] for x in horse],dtype=np.float32)
        age=np.asarray([x[2] for x in horse],dtype=np.float32)
        assign=np.asarray([x[3] for x in horse],dtype=np.float32)
        selected_indices=indices
        hnos=nums[selected_indices]
        logodds=np.log(odds)
        logselected=logodds[selected_indices]
        odd_geom=np.exp(np.sum(logselected*mask,axis=1)/span)
        odd_spread=np.max(np.where(mask,logselected,-1e5),axis=1)-\
                     np.min(np.where(mask,logselected,1e5),axis=1)
        ticket_age=np.sum(age[selected_indices]*mask,axis=1)/span
        ticket_weight=np.sum(assign[selected_indices]*mask,axis=1)/span
        ticket_draw=np.sum(hnos*mask,axis=1)/span
        own={
         'oddsGeom':np.digitize(odd_geom,odds_edges),
         'oddsSpread':np.digitize(odd_spread,[.2,.5,1.,1.6]),
         'horseAge':np.digitize(ticket_age,[3.2,4.2,5.2,7.2]),
         'draw':np.digitize(ticket_draw,[3,6,10,14]),
         'horseWeight':np.digitize(ticket_weight,[51,54,56,59]),
         'favOdds':np.full(N,np.digitize(odds[0],[1.6,2.2,3,4.5])),
         'favGap':np.full(N,np.digitize(odds[1]/odds[0],
                                      [1.2,1.7,2.5])),
         'venue':np.full(N,r['venue']-1),
         'fieldSize':np.full(N,np.digitize(len(r['horses']),
                                            [9,12,15])),
         'raceBand':np.full(N,min((r['raceNo']-1)//4,2)),
         'quarter':np.full(N,(int(r['month'][4:])-1)//3),
        }
        for k in SINGLE_BINS:
            categories[k][i]=(constant if k in constant else own)[k]
        for j,slot in enumerate(slots):
            m=int(markets[j])
            comb=tuple(int(nums[k]) for k in slot)
            if m in UNORDERED:comb=tuple(sorted(comb))
            paid[i,j]=r['payout'][m].get(comb,0)
        if (i+1)%5000==0:
            print('DECADE_CASH_FEATURE_FINISHED_RACES',i+1,flush=True)
    for k,maxval in SINGLE_BINS.items():
        if np.any(categories[k]>=maxval):
            raise RuntimeError('SIX_MARKET_CASH_CATEGORICAL_BIN_EXCEEDED:'+k)
    result={**categories,'market':np.broadcast_to(
                  markets,(n,N)).copy()}
    RACE_CACHE.write_text(json.dumps({'races':[{
         'id':r['id'],'month':r['month'],'day':r['day']} for r in races]},
         ensure_ascii=False),encoding='utf8')
    np.savez_compressed(CACHE,payout=paid,**result)
    print('DECADE_CASH_EXHAUSTIVE_FINISHED',json.dumps({
       'races':n,'tickets':n*N,'paidTickets':int(np.sum(paid>0)),
       '6markets':True,'yearsCovered':12,
       'newHorseWinPredictionUsed':False},ensure_ascii=False),flush=True)
    return paid,result

def mixed_code(features,columns):
    arr=features['market'].astype(np.int32)
    n=6
    for c in columns:
        arr*=SINGLE_BINS[c]
        arr+=features[c].astype(np.int32)
        n*=SINGLE_BINS[c]
    if n>10_000_000:raise RuntimeError('EXCESSIVE_CATEGORICAL_GROUP_SIZE')
    return arr,n

def mine(paid,features,races):
    dates=np.asarray([int(r['month'][:4]) for r in races],dtype=np.int16)
    train=(dates>=2015)&(dates<=2022)
    val=(dates==2023)
    train_mask=np.broadcast_to(train[:,None],paid.shape)
    val_mask=np.broadcast_to(val[:,None],paid.shape)
    trial={}
    audited=Counter()
    all_conditions=[]
    for col in PATTERNS:
        code,size=mixed_code(features,col)
        codes_train=code[train].ravel()
        ytrain=paid[train].ravel()
        codes_val=code[val].ravel()
        yval=paid[val].ravel()
        n=np.bincount(codes_train,minlength=size)
        cash=np.bincount(codes_train,weights=ytrain,minlength=size)
        hits=np.bincount(codes_train[ytrain>0],minlength=size)
        max_single=np.zeros(size,dtype=np.int32)
        np.maximum.at(max_single,codes_train[ytrain>0],ytrain[ytrain>0])
        valn=np.bincount(codes_val,minlength=size)
        val_cash=np.bincount(codes_val,weights=yval,minlength=size)
        val_hits=np.bincount(codes_val[yval>0],minlength=size)
        val_biggest=np.zeros(size,dtype=np.int32)
        np.maximum.at(val_biggest,codes_val[yval>0],yval[yval>0])
        robust=(cash-max_single)/np.maximum(n*100,1)
        val_robust=(val_cash-val_biggest)/np.maximum(valn*100,1)
        for size_floor in MIN_GROUP_SIZES:
            minwins=max(6,size_floor//35)
            groups=(n>=size_floor)&(hits>=minwins)&(robust>=2)
            audited['trainTrueRoi200Cells_support'+str(size_floor)]+=int(groups.sum())
            # Independent 2023 positive money stability, paid conditions
            # selected 2024 only. Never inspect 2025/26 outcomes here.
            qualifies=groups&(valn>=10)&(val_robust>=0)
            audited['train200And2023AnyObservedCashCells_support'+str(size_floor)]+=int(qualifies.sum())
            qualify_ids=np.flatnonzero(qualifies)
            for group in qualify_ids:
                historical=min(float(robust[group]),20.)
                held=min(float(val_robust[group]),20.)
                score=historical*(.3+held)*math.sqrt(
                   n[group]/(n[group]+200))*math.sqrt(
                   valn[group]/(valn[group]+50))
                all_conditions.append({
                    'columnSchema':col,'groupCode':int(group),
                    'minimumSupport':size_floor,
                    'train2015To2022Tickets':int(n[group]),
                    'train2015To2022RealCashRoiPct':round(
                        cash[group]/(n[group]),3),
                    'train2015To2022RoiWithoutMaxTicketPct':round(
                        100*robust[group],3),
                    '2023ValidationTickets':int(valn[group]),
                    '2023ValidationRoiWithoutMaxTicketPct':round(
                        100*val_robust[group],3),
                    'actualMonetaryRobustScore':round(score,7)})
        audited['searchedFinancialPatternSchemas']+=1
    # Same cell with different support threshold is the same actual rule.
    selected={}
    for cond in all_conditions:
        key=(tuple(cond['columnSchema']),cond['groupCode'])
        prior=selected.get(key)
        if prior is None or cond['minimumSupport']>prior['minimumSupport']:
            selected[key]=cond
    candidates=sorted(selected.values(),key=lambda q:(
        -q['actualMonetaryRobustScore'],-q['2023ValidationTickets']))
    audited['uniqueROI200FormConditionCellsFrom2015To2023']=len(candidates)
    audited['allCellsSelectedOn2015to2023HistoryOnly']=True
    return candidates,dict(audited)

def scores_from_subset(races,conditions,features,length):
    selected=conditions[:length]
    n=len(races)
    signal=np.zeros((n,N),dtype=np.float32)
    for cond in selected:
        arr,_=mixed_code(features,tuple(cond['columnSchema']))
        np.maximum(signal,
          np.where(arr==cond['groupCode'],cond['actualMonetaryRobustScore'],
                   0.).astype(np.float32),out=signal)
    return signal

def wager_options(races,payout,signal,period):
    out=defaultdict(list)
    for i,r in enumerate(races):
        if not period[0]<=r['month']<period[1]:continue
        picks=[]
        for m in range(6):
            x=int(START_MARKET[m]);y=int(START_MARKET[m+1])
            k=x+int(np.argmax(signal[i,x:y]))
            picks.append((float(signal[i,k]),i*N+k,m))
        out[r['day']].append((r['id'],i,picks))
    return out

def select_rows(days,rule):
    number,pair,stake,need_two,races_per_day=rule
    predictions=[]
    for day,records in days.items():
        best=[]
        for rid,i,choices in records:
            pairs=MARKET_PAIRS if pair<0 else (MARKET_PAIRS[pair],)
            top=None
            for a,b in pairs:
                p,q=choices[a],choices[b]
                if need_two and min(p[0],q[0])<=0:continue
                if p[0]+q[0]<=0:continue
                candidate=(p[0]+q[0],min(p[0],q[0]),-a,-b,
                           p[1],q[1])
                if top is None or candidate[:4]>top[:4]:top=candidate
            if top:
                best.append((top[0],rid,top[4],top[5]))
        best.sort(key=lambda z:(-z[0],z[1]))
        predictions.extend(best[:races_per_day])
    return predictions

def cash_audit(picks,payout,stake):
    if not picks:
        return {'races':0,'passes200':False}
    n=len(picks);investment=2000*n
    all_paid=payout.ravel()
    a=np.fromiter((all_paid[p[2]] for p in picks),
          dtype=np.int64,count=n)
    b=np.fromiter((all_paid[p[3]] for p in picks),
          dtype=np.int64,count=n)
    p1=a*(stake//100);p2=b*((2000-stake)//100)
    total=p1+p2
    gross=int(total.sum())
    pct=lambda x:round(100*x/investment,4)
    max_ticket=max(int(p1.max()),int(p2.max()))
    max_race=int(total.max())
    hit=float(np.mean(total>0))
    return {'races':n,'stakeYen':investment,'paidYen':gross,
        'profitYen':gross-investment,
        'roiPct':pct(gross),
        'roiMinusMaxTicketPct':pct(gross-max_ticket),
        'roiMinusMaxRacePct':pct(gross-max_race),
        'hitRacePct':round(hit*100,4),
        'passes200':bool(n>=100 and hit>=.2 and
          gross-max_ticket>=investment*2 and
          gross-max_race>=investment*2)}

def optimize(races,paid,conditions,features):
    if not conditions:return {'status':'NO_2015to2023_PROFITABLE_ROI200_CELLS'}
    sel_start='202401';sel_end='202501'
    f2025=('202501','202601');f2026=('202601','202605')
    selected=None;tried=0;eligible=0
    cache={}
    for n in SELECTIONS:
        sig=scores_from_subset(races,conditions,features,n)
        d=wager_options(races,paid,sig,(sel_start,sel_end))
        cache[n]=sig
        for pair,stake,need_two,maxr in product(
               MARKET_PAIR_CHOICES,STAKE_SPLITS,
               (False,True),NUMBER_RACES):
            rule=(n,pair,stake,need_two,maxr)
            rows=select_rows(d,rule)
            met=cash_audit(rows,paid,stake)
            tried+=1
            if met['races']<100 or met['hitRacePct']<20:continue
            eligible+=1
            # Choose by real money robustness over the entire 2024,
            # NOT on the 2025 / 2026 target.
            ranking=(int(met['passes200']),met['roiMinusMaxRacePct'],
                met['roiMinusMaxTicketPct'],met['roiPct'],met['races'])
            if selected is None or ranking>selected[0]:
                selected=(ranking,rule,met)
    if selected is None:
        return {'status':'NO_2024_RACES_100_HIT20_CANDIDATE',
           '2024StrategiesTried':tried,'eligible':eligible}
    _,rule,chosen2024=selected
    sig=cache[rule[0]]
    recent={}
    for name,p in (('2025FullYear',f2025),('2026JanApr',f2026)):
        days=wager_options(races,paid,sig,p)
        rows=select_rows(days,rule)
        recent[name]=cash_audit(rows,paid,rule[2])
        print('DECADE_ROI200_'+name+'_FROZEN',json.dumps(
             recent[name],ensure_ascii=False),flush=True)
    print('DECADE_ROI200_2024_SELECT',json.dumps({
        'rule':rule,'2024Money':chosen2024,
        'searched':tried,'qualifying2024':eligible,
        'shortlistedConditionCells':len(conditions)},ensure_ascii=False),flush=True)
    return {'status':'PASS' if all(
          z.get('passes200',False) for z in [chosen2024,*recent.values()])
         else 'NOT_200',
         '2024RuleSelection':{'maxCashConditions':rule[0],
           'marketPairIndex':rule[1],'firstTicketStakeYen':rule[2],
           'secondTicketStakeYen':2000-rule[2],
           'bothConditionsRequired':rule[3],
           'maximumRacesPerVenueDay':rule[4]},
         '2024PolicySearchCount':tried,
         '2024Eligible20PctHitStrategies':eligible,
         '2024CashSelectionOnly':chosen2024,
         **recent,
         'selectedHistoricalProfitableRules':conditions[:rule[0]],
         'both2025And2026CashRobust200':all(
           recent[k]['passes200'] for k in recent)}

def main():
    if '--self-test' in sys.argv:
        slots,mark=fixed_template()
        assert len(slots)==1030 and len(mark)==1030 and len(MARKET_PAIRS)==15
        assert len(PATTERNS)>60
        d=[{'month':'202401','day':'x','id':'a'}]
        f={k:np.zeros((1,N),dtype=(np.uint16 if k=='rankExact' else np.uint8))
                  for k in SINGLE_BINS}
        f['market']=np.broadcast_to(mark,(1,N))
        code,n=mixed_code(f,('rankMin','favOdds'))
        assert code.shape==(1,N) and n==6*10*5
        testpaid=np.zeros((1,N),dtype=np.int32)
        testpaid[0,0]=300
        cash=cash_audit([(0.,'r',0,1)],testpaid,1000)
        assert cash['roiPct']==150. and cash['stakeYen']==2000
        print('DECADE_REAL_CASH_ROI200_FIRST_MATH_OK',flush=True)
        return
    start=time.monotonic()
    if CACHE.exists() and RACE_CACHE.exists():
        with np.load(CACHE) as z:
            paid=z['payout']
            data={key:z[key] for key in (*SINGLE_BINS,'market')}
        races=json.loads(RACE_CACHE.read_text(encoding='utf8'))['races']
        print('DECADE_FIXED_MONEY_ARCHIVE_CACHE_HIT',len(races),flush=True)
    else:
        common=mod('scripts/research-nov2026-sixmarket-real-paid-cash.py',
                   'decade_historical_jra_actual_cash')
        races_all=read_all_races(common.parse_payments)
        CACHE.parent.mkdir(parents=True,exist_ok=True)
        paid,data=full_features(races_all)
        races=[{'id':r['id'],'month':r['month'],'day':r['day']}
               for r in races_all]
    if paid.shape!=(len(races),N):
        raise RuntimeError('DECADE_JRA_FINANCIAL_TICKET_ALIGNMENT')
    candidates,stats=mine(paid,data,races)
    print('DECADE_FINANCIAL_ROI200_CONDITIONS',json.dumps({
        'actualHistoricRaces':len(races),
        'independentActualPayoutCandidates':int(paid.size),
        'train2015To2022AndValidation2023':stats,
        'eligibleSelectedSingleRuleCells':len(candidates),
        'largestSupportedRules':candidates[:10]},
        ensure_ascii=False),flush=True)
    result=optimize(races,paid,candidates,data)
    result['discoverFirstBeforePredictions']=True
    result['actualPayoutArchive2015To2026JanApr']=True
    result['winnerPredictionFittedAtAnyStage']=False
    result['trainingHistoricalSample2015To2022']=True
    result['year2023CrossPeriodCashStabilityGate']=False
    result['policySelectionOnlyYear2024']=True
    result['untouchedOutOfYearCash2025And2026']=True
    result['allActualPayoutsThirdPartyNotOfficialReconciled']=True
    result['officialT15TicketCombinationOddsAvailable']=False
    result['2025And2026StudiedPreviouslyByOtherModelResearch']=True
    result['productionModified']=False
    result['adopted']=False
    result['seconds']=round(time.monotonic()-start,2)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',
                   encoding='utf8')
    print('DECADE_ROI200_FINANCIAL_MODEL_RESULT',OUT,flush=True)
if __name__=='__main__':main()
