#!/usr/bin/env python3
import argparse,collections,json,re,urllib.parse
from pathlib import Path

VENUE_CODE={'札幌':'01','函館':'02','福島':'03','新潟':'04','東京':'05','中山':'06','中京':'07','京都':'08','阪神':'09','小倉':'10'}
URL_RE=re.compile(r'(?:pw|sw)01sde(?:01|10)(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})',re.I)

def read_jsonl(p):
    with Path(p).open(encoding='utf-8') as f:
        for line in f:
            if line.strip():yield json.loads(line)
def identity(row):
    url=str((row.get('provenance') or {}).get('resultUrl') or row.get('resultUrl') or '')
    m=URL_RE.search(urllib.parse.unquote(url))
    if not m:return False,'UNPARSEABLE',url
    vc,year,meeting,day,rn,ymd=m.groups();date=str(row.get('raceDate') or '');venue=str(row.get('venue') or '')
    if ymd!=date.replace('-',''):return False,'DATE',url
    if int(rn)!=int(row.get('raceNo') or 0):return False,'RACE_NO',url
    if VENUE_CODE.get(venue) and vc!=VENUE_CODE[venue]:return False,'VENUE',url
    return True,None,url

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--selection',required=True);ap.add_argument('--reused',required=True);ap.add_argument('--fetched-dir',required=True);ap.add_argument('--out-dir',required=True);ap.add_argument('--meta',required=True);a=ap.parse_args()
    selected={str(r['raceId']):r for r in read_jsonl(a.selection)}
    if len(selected)!=14410:raise RuntimeError(f'SELECTION_INVALID:{len(selected)}')
    merged={};source=collections.Counter();dupes=[]
    for r in read_jsonl(a.reused):
        rid=str(r['raceId'])
        if rid in selected:merged[rid]=r;source['reused']+=1
    for p in sorted(Path(a.fetched_dir).glob('*.jsonl')):
        if p.name.endswith('-meta.jsonl'):continue
        for r in read_jsonl(p):
            rid=str(r['raceId'])
            if rid not in selected:continue
            if rid in merged:dupes.append(rid)
            merged[rid]=r;source['fetched']+=1
    missing=sorted(set(selected)-set(merged));extra=sorted(set(merged)-set(selected));bad=[];synthetic=[]
    for rid,r in merged.items():
        ok,reason,url=identity(r)
        if not ok:bad.append({'raceId':rid,'reason':reason,'url':url})
        prov=r.get('provenance') or {}
        if prov.get('syntheticOddsUsed') is True or r.get('syntheticOddsUsed') is True:synthetic.append(rid)
        if not (r.get('officialOdds') or {}).get('win'):bad.append({'raceId':rid,'reason':'WIN_ODDS_MISSING','url':url})
    out=Path(a.out_dir);out.mkdir(parents=True,exist_ok=True)
    byyear=collections.defaultdict(list)
    for rid,r in merged.items():byyear[str(r['raceDate'])[:4]].append(r)
    for y,rows in sorted(byyear.items()):
        rows.sort(key=lambda r:(r['raceDate'],str(r.get('venue') or ''),int(r.get('raceNo') or 0)))
        with (out/f'research-meta-market-odds-{y}.jsonl').open('w',encoding='utf-8') as f:
            for r in rows:f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')
    meta={'purpose':'research_only_meta_selected_source_audited_official_odds','selectedRaces':len(selected),'mergedOddsRaces':len(merged),'missingRaceIds':missing,'extraRaceIds':extra,'duplicateFetchedVsReused':dupes,'sourceCounts':dict(source),'identityMismatchRows':bad,'syntheticOddsRaceIds':synthetic,'byYear':{y:len(v) for y,v in sorted(byyear.items())},'historicalFinalOddsUsed':True,'prestartTimingValidationPerformed':False,'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False}
    Path(a.meta).parent.mkdir(parents=True,exist_ok=True);Path(a.meta).write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(meta,ensure_ascii=False),flush=True)
    if missing or extra or bad or synthetic or len(merged)!=14410:raise RuntimeError(f'MERGE_AUDIT_FAILED:missing={len(missing)} extra={len(extra)} bad={len(bad)} synthetic={len(synthetic)} merged={len(merged)}')
if __name__=='__main__':main()
