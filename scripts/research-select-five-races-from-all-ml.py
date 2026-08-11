#!/usr/bin/env python3
import argparse,collections,json,math
from pathlib import Path

VARIANTS=('confidence','concentration','disagreement','hybrid')

def zmap(items,key):
    vals=[float(x[key]) for x in items];m=sum(vals)/len(vals);v=sum((x-m)**2 for x in vals)/max(1,len(vals));s=math.sqrt(v)
    if s<1e-12:return {x['raceId']:0.0 for x in items}
    return {x['raceId']:(float(x[key])-m)/s for x in items}

def race_summary(rows):
    ordered=sorted(rows,key=lambda r:(-float(r['abilityScore']),int(r['horseNo'])))
    if len(ordered)<3:return None
    a1,a2,a3=[float(ordered[i]['abilityScore']) for i in range(3)]
    field=max(1,int(ordered[0].get('fieldSize') or len(ordered)))
    pop=float(ordered[0].get('marketPopularity') or field+1)
    pop=max(1.0,pop)
    return {
      'raceId':str(ordered[0]['raceId']),'raceDate':str(ordered[0]['raceDate']),'venueCode':int(ordered[0].get('venueCode') or 0),'raceNo':int(ordered[0].get('raceNo') or 0),
      'fieldSize':field,'topAbilityHorseNo':int(ordered[0]['horseNo']),'topAbilityMarketPopularity':pop,
      'margin12':a1-a2,'margin13':a1-a3,'concentration':a1-(a2+a3)/2.0,
      'disagreementRaw':((pop-1.0)/max(1.0,field-1.0))*max(0.0,a1-a2),
    }

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--predictions-dir',required=True);ap.add_argument('--out-dir',required=True);ap.add_argument('--summary',required=True);a=ap.parse_args()
    by_race=collections.defaultdict(list)
    for p in sorted(Path(a.predictions_dir).glob('all-race-ranker-20*.jsonl')):
        for line in p.read_text(encoding='utf-8').splitlines():
            if line.strip():
                r=json.loads(line);by_race[str(r['raceId'])].append(r)
    races=[]
    for rows in by_race.values():
        s=race_summary(rows)
        if s:races.append(s)
    groups=collections.defaultdict(list)
    for r in races:groups[(r['raceDate'],r['venueCode'])].append(r)
    selected={v:[] for v in VARIANTS};structural=[]
    for key,rs in sorted(groups.items()):
        rs=sorted(rs,key=lambda r:(r['raceNo'],r['raceId']))
        if len(rs)<5:
            structural.append({'raceDate':key[0],'venueCode':key[1],'eligibleRaces':len(rs),'raceIds':[r['raceId'] for r in rs]});continue
        zm=zmap(rs,'margin12');zc=zmap(rs,'concentration');zd=zmap(rs,'disagreementRaw')
        for r in rs:
            r['scoreConfidence']=r['margin12']
            r['scoreConcentration']=r['concentration']
            r['scoreDisagreement']=r['disagreementRaw']
            r['scoreHybrid']=zm[r['raceId']]+0.5*zd[r['raceId']]+0.25*zc[r['raceId']]
        keymap={'confidence':'scoreConfidence','concentration':'scoreConcentration','disagreement':'scoreDisagreement','hybrid':'scoreHybrid'}
        for v in VARIANTS:
            pick=sorted(rs,key=lambda r:(-r[keymap[v]],r['raceNo'],r['raceId']))[:5]
            for r in pick:
                selected[v].append({k:r[k] for k in ('raceId','raceDate','venueCode','raceNo','fieldSize','topAbilityHorseNo','topAbilityMarketPopularity','margin12','margin13','concentration','disagreementRaw','scoreConfidence','scoreConcentration','scoreDisagreement','scoreHybrid')}|{'variant':v,'targetRaceResultUsedForSelection':False,'targetRacePayoutUsedForSelection':False,'historicalFinalPopularityUsedForSelection':v in ('disagreement','hybrid')})
    outdir=Path(a.out_dir);outdir.mkdir(parents=True,exist_ok=True)
    for v,rows in selected.items():
        p=outdir/f'ml-five-selection-{v}.jsonl';p.write_text(''.join(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n' for r in rows),encoding='utf-8')
    summary={'purpose':'research_only_result_blind_five_race_selection_from_all_race_ml','predictionRaces':len(races),'venueDays':len(groups),'structuralShortVenueDays':structural,'variants':{},'targetRaceResultUsedForSelection':False,'targetRacePayoutUsedForSelection':False,'productionDatabaseWritten':False,'productionModelChanged':False}
    for v,rows in selected.items():
        dup=len(rows)-len({r['raceId'] for r in rows});summary['variants'][v]={'selectedRaces':len(rows),'duplicateRaceIds':dup,'historicalFinalPopularityUsedForSelection':v in ('disagreement','hybrid'),'prestartPopularityTimingValidationPerformed':False if v in ('disagreement','hybrid') else None}
    Path(a.summary).write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
