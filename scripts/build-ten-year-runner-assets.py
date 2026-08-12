#!/usr/bin/env python3
import argparse,gzip,json
from collections import defaultdict
from pathlib import Path

START='2016-08-10'
END='2026-08-09'
EXPECTED_RACES=34566


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--history',required=True)
    ap.add_argument('--out-dir',required=True)
    a=ap.parse_args()
    out=Path(a.out_dir);out.mkdir(parents=True,exist_ok=True)
    for p in out.glob('*.json.gz'):p.unlink()
    months=defaultdict(list);race_count=0;runner_count=0
    with open(a.history,encoding='utf-8') as f:
        for line in f:
            if not line.strip():continue
            b=json.loads(line);r=b['race'];date=str(r['raceDate'])
            if not (START<=date<=END):continue
            rid=str(r['raceId']);res={int(x.get('horseNo')):x for x in b.get('results',[]) if x.get('horseNo') is not None}
            runners=[]
            for x in b.get('runners',[]):
                h=int(x.get('horseNo') or 0);z=res.get(h,{})
                runners.append([
                    h,int(x.get('frameNo') or 0),x.get('horseName'),x.get('sexAge'),x.get('assignedWeight'),
                    x.get('jockey'),x.get('trainer'),x.get('horseWeight'),x.get('weightChange'),x.get('popularity'),
                    x.get('winOdds'),z.get('finishPosition'),z.get('timeText'),z.get('final3f'),x.get('runnerStatus')
                ])
                runner_count+=1
            months[date[:7]].append([rid,runners]);race_count+=1
    if race_count!=EXPECTED_RACES:raise RuntimeError(f'RACE_COUNT:{race_count}')
    manifest={}
    for month,rows in sorted(months.items()):
        path=out/f'{month}.json.gz'
        raw=json.dumps(rows,ensure_ascii=False,separators=(',',':')).encode()
        with gzip.GzipFile(filename='',mode='wb',fileobj=open(path,'wb'),compresslevel=9,mtime=0) as g:g.write(raw)
        manifest[month]={'races':len(rows),'bytes':path.stat().st_size}
    (out/'manifest.json').write_text(json.dumps({'start':START,'end':END,'races':race_count,'runners':runner_count,'months':manifest},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'races':race_count,'runners':runner_count,'months':len(months),'bytes':sum(x['bytes'] for x in manifest.values())},ensure_ascii=False))

if __name__=='__main__':main()
