#!/usr/bin/env python3
import argparse,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
START='2016-08-10'; END='2026-08-09'
MARKETS=['win','umaren','wide','umatan','trio','trifecta']

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--corpus',required=True); ap.add_argument('--out',required=True); ap.add_argument('--meta',required=True); a=ap.parse_args()
    rows=[]
    with (ROOT/a.corpus).open(encoding='utf-8') as fh:
        for line in fh:
            if not line.strip(): continue
            b=json.loads(line); r=b.get('race') or {}; d=str(r.get('raceDate') or '')
            if not (START<=d<=END): continue
            u=r.get('resultUrl') or (b.get('provenance') or {}).get('resultUrl')
            if not u: raise RuntimeError(f"RESULT_URL_MISSING:{r.get('raceId')}")
            rows.append({'raceId':str(r['raceId']),'raceDate':d,'venue':r.get('venue'),'raceNo':r.get('raceNo'),'resultUrl':u,'requiredMarkets':MARKETS})
    rows.sort(key=lambda x:(x['raceDate'],str(x['venue']),int(x['raceNo'] or 0)))
    if len(rows)!=34566 or len({x['raceId'] for x in rows})!=len(rows): raise RuntimeError(f'BAD_MANIFEST:{len(rows)}')
    out=ROOT/a.out; out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(''.join(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n' for x in rows),encoding='utf-8')
    by={}
    for x in rows: by[x['raceDate'][:4]]=by.get(x['raceDate'][:4],0)+1
    m={'purpose':'research_only_full_history_official_odds_manifest','evaluationStart':START,'evaluationEnd':END,'raceCount':len(rows),'byYear':by,'requiredMarkets':MARKETS,'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False}
    (ROOT/a.meta).write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(m,ensure_ascii=False),flush=True)
if __name__=='__main__': main()
