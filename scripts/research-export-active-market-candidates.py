#!/usr/bin/env python3
import argparse,collections,importlib.util,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def load(path,name):
    s=importlib.util.spec_from_file_location(name,path)
    if s is None or s.loader is None:raise RuntimeError(f'MODULE_LOAD_FAILED:{path}')
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

cmod=load(ROOT/'scripts/research-continuous-walkforward-demand.py','candidate_export_cont')
dist=load(ROOT/'scripts/research-evaluate-market-distortion-roi.py','candidate_export_dist')
smod=dist.smod;dmod=dist.dmod


def load_odds(path):
    out={}
    for p in sorted(Path(path).glob('research-continuous-market-odds-20*.jsonl')):
        for line in p.read_text(encoding='utf-8').splitlines():
            if line.strip():
                r=json.loads(line);rid=str(r['raceId'])
                if rid in out:raise RuntimeError(f'DUPLICATE_ODDS:{rid}')
                out[rid]=r
    return out


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--corpus',required=True);ap.add_argument('--demand',required=True);ap.add_argument('--odds-dir',required=True);ap.add_argument('--out',required=True);ap.add_argument('--meta',required=True);a=ap.parse_args()
    demand={}
    for line in (ROOT/a.demand).read_text(encoding='utf-8').splitlines():
        if line.strip():
            r=json.loads(line);demand[str(r['raceId'])]=r
    if len(demand)!=14410:raise RuntimeError(f'DEMAND_COUNT_INVALID:{len(demand)}')
    odds=load_odds(ROOT/a.odds_dir)
    if set(odds)!=set(demand):raise RuntimeError(f'ODDS_DEMAND_SET_MISMATCH:{len(odds)}:{len(demand)}')
    state={'horse_hist':collections.defaultdict(lambda:collections.deque(maxlen=3)),'horse_starts':collections.Counter(),'jstats':collections.defaultdict(lambda:[0,0]),'tstats':collections.defaultdict(lambda:[0,0])}
    outp=ROOT/a.out;outp.parent.mkdir(parents=True,exist_ok=True)
    fhout=outp.open('w',encoding='utf-8')
    current=None;day=[];seen=set();ticket_count=0;by_year=collections.Counter();candidate_counts=collections.Counter()

    def process(date,bundles):
        nonlocal ticket_count
        for b in bundles:
            race=b['race'];rid=str(race['raceId'])
            if rid not in demand:continue
            seen.add(rid);o=odds[rid];active={int(x) for x in (o.get('horses') or [])}
            source=dict(b);source['runners']=[r for r in b.get('runners',[]) if int(r['horseNo']) in active]
            raw=cmod.candidate_rows(state,source)
            raw=[t for t in raw if all(int(h) in active for h in t['horses'])]
            enriched=dist.enrich_candidates(raw,o)
            if len(enriched)<3 or len({t['bt'] for t in enriched})<2:raise RuntimeError(f'CANDIDATE_GATE:{rid}:{len(enriched)}')
            pays=smod.payout_index(b);tickets=[]
            for t in enriched:
                keys=[]
                for key in dist.extended_keys(t):
                    bt,axes,vals=key;keys.append([bt,list(axes),list(vals)])
                tickets.append({'bt':t['bt'],'market':t['market'],'betType':t['betType'],'horses':t['horses'],'combo':t['combo'],'vals':t['vals'],'odds':t['odds'],'oddsBin':t['oddsBin'],'marketRank':t.get('marketRank'),'distortRatio':t.get('distortRatio'),'payoutPer100Yen':int(pays.get((t['betType'],t['combo']),0) or 0),'ruleKeys':keys})
            row={'raceId':rid,'raceDate':date,'venue':race.get('venue'),'raceNo':race.get('raceNo'),'activeHorseCount':len(active),'candidateCount':len(tickets),'tickets':tickets,'targetRaceOutcomeUsedForFeatures':False,'historicalFinalOddsUsedForMarketFeatures':True,'syntheticOddsUsed':False}
            fhout.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n');ticket_count+=len(tickets);by_year[date[:4]]+=1;candidate_counts[len(tickets)]+=1
        dmod.update_state_for_date(state,bundles)

    with (ROOT/a.corpus).open(encoding='utf-8') as fh:
        for line in fh:
            if not line.strip():continue
            b=json.loads(line);date=str(b['race'].get('raceDate') or '')
            if current is None:current=date
            if date!=current:process(current,day);day=[];current=date
            day.append(b)
    if current:process(current,day)
    fhout.close()
    missing=sorted(set(demand)-seen)
    if missing:raise RuntimeError(f'MISSING_SELECTED_RACES:{len(missing)}:{missing[:20]}')
    meta={'purpose':'research_only_source_clean_active_reranked_market_candidate_corpus','selectedRaces':len(seen),'candidateTickets':ticket_count,'racesByYear':dict(sorted(by_year.items())),'candidateCountDistribution':{str(k):v for k,v in sorted(candidate_counts.items())},'activeRunnersFilteredBeforeRanking':True,'targetRaceOutcomeUsedForFeatures':False,'historicalFinalOddsUsedForMarketFeatures':True,'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False}
    (ROOT/a.meta).write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(meta,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
