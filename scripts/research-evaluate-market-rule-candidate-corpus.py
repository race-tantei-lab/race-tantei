#!/usr/bin/env python3
import argparse,collections,json,math
from pathlib import Path

COURSES={'ライト':2000,'スタンダード':5000,'プレミアム':10000}
CAPS=(2000,5000);MIN_NS=(100,300);ZS=(0.0,0.75,1.5);AGGS=('top1','top3')
PRIOR_N=500.0;PRIOR_ROI=0.80;TOP_RULES=3
VARIANTS=[(cap,n,z,agg) for cap in CAPS for n in MIN_NS for z in ZS for agg in AGGS]
ODDS_EDGES=(5,8,12,20,35,60,100,180,300,600,1200)


def bsearch(edges,x):
    i=0
    while i<len(edges) and x>=edges[i]:i+=1
    return i

def weight_for_bin(bin_id):return 1.0/(1.0+0.25*max(0,bin_id-2))
def allocate(odds_bins,total_units):
    weights=[weight_for_bin(b) for b in odds_bins];s=sum(weights);raw=[w/s*total_units for w in weights];units=[max(1,int(x)) for x in raw]
    while sum(units)>total_units:
        i=max(range(len(units)),key=lambda j:(units[j]-raw[j],units[j]));
        if units[i]<=1:break
        units[i]-=1
    while sum(units)<total_units:
        i=max(range(len(units)),key=lambda j:(raw[j]-units[j],-units[j]));units[i]+=1
    return units

def period(date):
    y=int(date[:4])
    if date<='2018-12-31':return '2016-08-10..2018'
    if y<=2021:return '2019..2021'
    if y<=2024:return '2022..2024'
    return '2025..2026-08-09'

def init_stat():return {'races':0,'tickets':0,'hitRaces':0,'stakeYen':0,'returnYen':0}
def add(s,stake,ret,n):s['races']+=1;s['tickets']+=n;s['hitRaces']+=int(ret>0);s['stakeYen']+=stake;s['returnYen']+=ret
def fin(s):
    x=dict(s);x['profitYen']=s['returnYen']-s['stakeYen'];x['roiPct']=round(100*s['returnYen']/s['stakeYen'],4) if s['stakeYen'] else None;x['hitRacePct']=round(100*s['hitRaces']/s['races'],4) if s['races'] else None;return x

def stat_record():return [0.0,0.0,0.0,0.0,0.0]
def upd(s,x2,x5):s[0]+=1;s[1]+=x2;s[2]+=x2*x2;s[3]+=x5;s[4]+=x5*x5
def capstat(s,cap):return (s[0],s[1],s[2]) if cap==2000 else (s[0],s[3],s[4])
def base_mean(s,cap):
    if not s or s[0]<=0:return PRIOR_ROI
    n,v,_=capstat(s,cap);return (v+PRIOR_N*PRIOR_ROI)/(n+PRIOR_N)
def insert3(a,v):
    if len(a)<3:a.append(v);a.sort(reverse=True)
    elif v>a[-1]:a[-1]=v;a.sort(reverse=True)

def norm_key(raw):return (int(raw[0]),tuple(raw[1]),tuple(raw[2]))
def baseline_key(t):return (int(t['bt']),int(t['vals']['odds']))

def scores_for_ticket(t,rule_stats,base_stats):
    bases={cap:base_mean(base_stats.get(baseline_key(t)),cap) for cap in CAPS}
    top={(cap,n,z):[] for cap in CAPS for n in MIN_NS for z in ZS}
    for raw in t['ruleKeys']:
        rec=rule_stats.get(norm_key(raw))
        if not rec or rec[0]<100:continue
        n=rec[0]
        for cap in CAPS:
            _,s,ss=capstat(rec,cap);bm=bases[cap];mean=(s+PRIOR_N*bm)/(n+PRIOR_N);rawm=s/n;var=max(0.0,ss/n-rawm*rawm) if n>1 else 0.0;se=math.sqrt(var/max(1.0,n+PRIOR_N))
            for mn in MIN_NS:
                if n<mn:continue
                for z in ZS:insert3(top[(cap,mn,z)],mean-z*se)
    out={}
    for cap in CAPS:
        for mn in MIN_NS:
            for z in ZS:
                a=top[(cap,mn,z)];out[(cap,mn,z,'top1')]=a[0] if a else bases[cap];out[(cap,mn,z,'top3')]=sum(a[:3])/len(a[:3]) if a else bases[cap]
    return out

def select(tickets,scores):
    ranked=[(scores[i],float(t['odds']),int(t['bt']),str(t['combo']),i) for i,t in enumerate(tickets)];ranked.sort(key=lambda x:(-x[0],x[1],x[2],x[3]))
    mx=ranked[0][0];idx=[x[4] for x in ranked if x[0]>=mx*0.92-1e-12][:10]
    if len(idx)<3:idx=[x[4] for x in ranked[:3]]
    types={int(tickets[i]['bt']) for i in idx}
    if len(types)<2:
        alt=next((x[4] for x in ranked if x[4] not in idx and int(tickets[x[4]]['bt']) not in types),None)
        if alt is None:raise RuntimeError('NO_SECOND_BET_TYPE')
        if len(idx)<10:idx.append(alt)
        else:idx[-1]=alt
    idx.sort(key=lambda i:(-scores[i],float(tickets[i]['odds']),int(tickets[i]['bt']),str(tickets[i]['combo'])))
    if not(3<=len(idx)<=10) or len({int(tickets[i]['bt']) for i in idx})<2:raise RuntimeError('FINAL_TICKET_GATE_FAILED')
    return idx

def settle(tickets,idx,budget):
    bins=[int(tickets[i]['oddsBin']) for i in idx];units=allocate(bins,budget//100)
    if sum(units)*100!=budget:raise RuntimeError('BUDGET_INVALID')
    return sum(units[j]*int(tickets[i]['payoutPer100Yen']) for j,i in enumerate(idx))
def concentration(rows,total):
    r=sorted(rows,key=lambda x:x['returnYen'],reverse=True)
    def pct(n):return round(100*sum(x['returnYen'] for x in r[:n])/total,4) if total else 0.0
    return {'largestRaceReturnYen':r[0]['returnYen'] if r else 0,'largestRaceId':r[0]['raceId'] if r else None,'top1ReturnSharePct':pct(1),'top5ReturnSharePct':pct(5),'top10ReturnSharePct':pct(10),'top25ReturnSharePct':pct(25)}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--candidates',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    rows=[json.loads(x) for x in Path(a.candidates).read_text(encoding='utf-8').splitlines() if x.strip()]
    if len(rows)!=14410:raise RuntimeError(f'CANDIDATE_RACE_COUNT:{len(rows)}')
    rows.sort(key=lambda r:(r['raceDate'],r['venue'],int(r['raceNo'])))
    overall={(v,c):init_stat() for v in VARIANTS for c in COURSES};yearly={(v,c):collections.defaultdict(init_stat) for v in VARIANTS for c in COURSES};periods={(v,c):collections.defaultdict(init_stat) for v in VARIANTS for c in COURSES};rets={(v,c):[] for v in VARIANTS for c in COURSES};errors={v:[] for v in VARIANTS}
    rule_stats=collections.defaultdict(stat_record);base_stats=collections.defaultdict(stat_record)
    cur=None;day=[]
    def process(date,rs):
        prepared=[]
        for r in rs:
            tickets=r['tickets'];scorelists={v:[] for v in VARIANTS};keylists=[]
            for t in tickets:
                sc=scores_for_ticket(t,rule_stats,base_stats);keylists.append([norm_key(x) for x in t['ruleKeys']])
                for v in VARIANTS:scorelists[v].append(sc[v])
            prepared.append((r,keylists))
            for v in VARIANTS:
                try:
                    idx=select(tickets,scorelists[v])
                    for c,budget in COURSES.items():
                        ret=settle(tickets,idx,budget);add(overall[(v,c)],budget,ret,len(idx));add(yearly[(v,c)][date[:4]],budget,ret,len(idx));add(periods[(v,c)][period(date)],budget,ret,len(idx));rets[(v,c)].append({'raceId':r['raceId'],'returnYen':ret})
                except Exception as e:errors[v].append({'raceId':r['raceId'],'error':f'{type(e).__name__}:{e}'})
        for r,keylists in prepared:
            for t,keys in zip(r['tickets'],keylists):
                pay=int(t['payoutPer100Yen']);x2=min(pay,2000)/100.0;x5=min(pay,5000)/100.0;upd(base_stats[baseline_key(t)],x2,x5)
                for key in keys:upd(rule_stats[key],x2,x5)
    for r in rows:
        d=r['raceDate']
        if cur is None:cur=d
        if d!=cur:process(cur,day);day=[];cur=d
        day.append(r)
    if day:process(cur,day)
    rv={}
    for v in VARIANTS:
        cap,mn,z,agg=v;name=f'cap{cap}-n{mn}-z{z:.2f}-{agg}';courses={}
        for c in COURSES:
            x=fin(overall[(v,c)]);x['byYear']={y:fin(s) for y,s in sorted(yearly[(v,c)].items())};x['byPeriod']={p:fin(s) for p,s in periods[(v,c)].items()};x['returnConcentration']=concentration(rets[(v,c)],overall[(v,c)]['returnYen']);courses[c]=x
        rv[name]={'trainingCap':cap,'minRuleN':mn,'lcbZ':z,'aggregation':agg,'evaluatedRaces':courses['ライト']['races'],'evaluationErrorCount':len(errors[v]),'evaluationErrors':errors[v][:100],'courses':courses,'completeOddsAndEvaluation':len(errors[v])==0,'allThreeAtLeast200Pct':len(errors[v])==0 and all((courses[c]['roiPct'] or 0)>=200 for c in COURSES)}
    ranking=sorted(rv,key=lambda k:(rv[k]['completeOddsAndEvaluation'],min(rv[k]['courses'][c]['roiPct'] or 0 for c in COURSES),sum(rv[k]['courses'][c]['roiPct'] or 0 for c in COURSES)),reverse=True)
    out={'purpose':'research_only_dynamic_market_rule_from_fixed_candidate_corpus','selectedDemandRaces':14410,'candidateCorpusFrozenBeforeExploration':True,'sameDayResultsUsedForTicketRule':False,'productionRulesReused':False,'trainingReturnCapped':True,'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False,'variants':rv,'ranking':ranking,'bestVariant':ranking[0]}
    Path(a.out).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');b=out['bestVariant'];print(json.dumps({'best':b,'roi':{c:rv[b]['courses'][c]['roiPct'] for c in COURSES},'errors':rv[b]['evaluationErrorCount']},ensure_ascii=False))
if __name__=='__main__':main()
