#!/usr/bin/env python3
import argparse,collections,json,re,urllib.parse
from pathlib import Path

MARKETS=('win','umaren','wide','umatan','trio','trifecta')
VENUE_CODE={'札幌':'01','函館':'02','福島':'03','新潟':'04','東京':'05','中山':'06','中京':'07','京都':'08','阪神':'09','小倉':'10'}
URL_RE=re.compile(r'(?:pw|sw)01sde(?:01|10)(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})',re.I)

def read_jsonl(path):
    with Path(path).open(encoding='utf-8') as f:
        for line in f:
            if line.strip():yield json.loads(line)

def write_jsonl(path,rows):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8') as f:
        for r in rows:f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')

def identity_ok(row):
    url=str((row.get('provenance') or {}).get('resultUrl') or row.get('resultUrl') or '')
    m=URL_RE.search(urllib.parse.unquote(url))
    if not m:return False,'URL_ID_UNPARSEABLE'
    vc,year,meeting,day,rn,ymd=m.groups()
    expect_v=VENUE_CODE.get(str(row.get('venue') or ''))
    if ymd!=str(row.get('raceDate') or '').replace('-',''):return False,'DATE_MISMATCH'
    if int(rn)!=int(row.get('raceNo') or 0):return False,'RACE_NO_MISMATCH'
    if expect_v and vc!=expect_v:return False,'VENUE_MISMATCH'
    return True,None

def canonical_result_url(race):
    venue=str(race.get('venue') or '');date=str(race.get('raceDate') or '');ymd=date.replace('-','')
    if venue not in VENUE_CODE or len(ymd)!=8:raise RuntimeError(f'RACE_IDENTITY_INVALID:{race}')
    if race.get('meetingNo') is None or race.get('meetingDay') is None:raise RuntimeError(f'MEETING_META_MISSING:{race.get("raceId")}')
    identity=f"{VENUE_CODE[venue]}{ymd[:4]}{int(race['meetingNo']):02d}{int(race['meetingDay']):02d}{int(race['raceNo']):02d}{ymd}"
    return 'https://www.jra.go.jp/JRADB/accessS.html?CNAME='+urllib.parse.quote('pw01sde10'+identity,safe='')

def load_odds_dir(path,patterns):
    out={}
    for pat in patterns:
        for p in sorted(Path(path).glob(pat)):
            for r in read_jsonl(p):out[str(r['raceId'])]=r
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--selection',required=True);ap.add_argument('--history',required=True);ap.add_argument('--continuous-odds-dir',required=True);ap.add_argument('--canonical-odds-dir',required=True);ap.add_argument('--predictions-dir',required=True);ap.add_argument('--reused-out',required=True);ap.add_argument('--missing-out',required=True);ap.add_argument('--history-out',required=True);ap.add_argument('--predictions-out',required=True);ap.add_argument('--meta',required=True);a=ap.parse_args()
    sel=list(read_jsonl(a.selection));selected={str(r['raceId']):r for r in sel}
    if len(selected)!=14410:raise RuntimeError(f'SELECTION_COUNT_INVALID:{len(selected)}')
    hist={}
    for b in read_jsonl(a.history):
        rid=str((b.get('race') or {}).get('raceId') or '')
        if rid in selected:hist[rid]=b
    if len(hist)!=14410:raise RuntimeError(f'SELECTED_HISTORY_MISSING:{14410-len(hist)}')
    pred=collections.defaultdict(list)
    for p in sorted(Path(a.predictions_dir).glob('all-race-ranker-20*.jsonl')):
        for r in read_jsonl(p):
            rid=str(r['raceId'])
            if rid in selected:pred[rid].append(r)
    if len(pred)!=14410:raise RuntimeError(f'SELECTED_PREDICTIONS_MISSING:{14410-len(pred)}')
    continuous=load_odds_dir(a.continuous_odds_dir,['research-continuous-market-odds-20*.jsonl'])
    canonical=load_odds_dir(a.canonical_odds_dir,['research-demanded-odds-20*.jsonl'])
    reused={};source_counts=collections.Counter();rejected=[]
    # Lower-priority canonical first. It is reused only when source identity matches.
    for rid in selected:
        r=canonical.get(rid)
        if not r:continue
        ok,reason=identity_ok(r)
        if not ok:
            rejected.append({'raceId':rid,'source':'canonical297','reason':reason});continue
        if not (r.get('officialOdds') or {}).get('win'):
            rejected.append({'raceId':rid,'source':'canonical297','reason':'WIN_ODDS_MISSING'});continue
        reused[rid]=r;source_counts['canonical297']+=1
    # Audited source-clean continuous rows override canonical rows.
    for rid in selected:
        r=continuous.get(rid)
        if not r:continue
        ok,reason=identity_ok(r)
        if not ok:raise RuntimeError(f'SOURCE_CLEAN_IDENTITY_REGRESSION:{rid}:{reason}')
        if not (r.get('officialOdds') or {}).get('win'):raise RuntimeError(f'SOURCE_CLEAN_WIN_MISSING:{rid}')
        if rid in reused:source_counts['canonical297']-=1
        reused[rid]=r;source_counts['continuousSourceClean']+=1
    missing=[]
    for rid in sorted(set(selected)-set(reused),key=lambda x:(selected[x]['raceDate'],x)):
        race=hist[rid]['race'];url=canonical_result_url(race)
        missing.append({'raceId':rid,'raceDate':str(race['raceDate']),'venue':str(race['venue']),'raceNo':int(race['raceNo']),'entryUrl':race.get('entryUrl') or (hist[rid].get('provenance') or {}).get('entryUrl'),'resultUrl':url,'requiredMarkets':list(MARKETS),'resultUrlResolutionMethod':'reconstructed_from_verified_race_identity','targetDayResultsUsedForSelection':False,'syntheticOddsUsed':False,'productionDatabaseWritten':False})
    reused_rows=[reused[rid] for rid in sorted(reused,key=lambda x:(selected[x]['raceDate'],x))]
    selected_hist=[hist[rid] for rid in sorted(selected,key=lambda x:(selected[x]['raceDate'],x))]
    selected_pred=[r for rid in sorted(pred,key=lambda x:(selected[x]['raceDate'],x)) for r in pred[rid]]
    write_jsonl(a.reused_out,reused_rows);write_jsonl(a.missing_out,missing);write_jsonl(a.history_out,selected_hist);write_jsonl(a.predictions_out,selected_pred)
    by_year=collections.Counter(r['raceDate'][:4] for r in missing)
    meta={'purpose':'research_only_audited_meta_market_input','selectedRaces':14410,'reusedOddsRaces':len(reused),'missingOddsRaces':len(missing),'reusedSourceCounts':dict(source_counts),'missingByYear':dict(sorted(by_year.items())),'rejectedReuseRows':rejected,'allMissingResultUrlsReconstructedFromRaceIdentity':True,'allMissingRequiredMarkets':list(MARKETS),'selectedPredictionRaces':len(pred),'selectedPredictionRows':len(selected_pred),'selectedHistoryRaces':len(selected_hist),'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False}
    Path(a.meta).parent.mkdir(parents=True,exist_ok=True);Path(a.meta).write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(meta,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
