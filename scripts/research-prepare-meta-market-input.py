#!/usr/bin/env python3
import argparse,collections,json,re,urllib.parse
from pathlib import Path

MARKETS=('win','umaren','wide','umatan','trio','trifecta')
VENUE_CODE={'札幌':'01','函館':'02','福島':'03','新潟':'04','東京':'05','中山':'06','中京':'07','京都':'08','阪神':'09','小倉':'10'}
RESULT_RE=re.compile(r'(?:pw|sw)01sde(?:01|10)(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})',re.I)
ENTRY_RE=re.compile(r'(?:pw|sw)01dde(?:01|10)(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})',re.I)
ODDS_RE=re.compile(r'(?:pw|sw)15[1-8]ou10(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})',re.I)

def read_jsonl(path):
    with Path(path).open(encoding='utf-8') as f:
        for line in f:
            if line.strip():yield json.loads(line)

def write_jsonl(path,rows):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8') as f:
        for r in rows:f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')

def groups_match(m,date,venue,race_no):
    if not m:return False
    vc,year,meeting,day,rn,ymd=m.groups()
    return ymd==str(date).replace('-','') and int(rn)==int(race_no) and (not VENUE_CODE.get(str(venue)) or vc==VENUE_CODE[str(venue)])

def identity_match(row):
    prov=row.get('provenance') or {}
    candidates=[str(prov.get('resultUrl') or ''),str(row.get('resultUrl') or '')]
    source=prov.get('sourceCnames') or {}
    if isinstance(source,dict):candidates.extend(str(v or '') for v in source.values())
    for text in candidates:
        decoded=urllib.parse.unquote(text)
        m=RESULT_RE.search(decoded) or ODDS_RE.search(decoded)
        if m:return m,text
    return None,''

def identity_ok(row):
    m,_=identity_match(row)
    if not m:return False,'SOURCE_ID_UNPARSEABLE'
    vc,year,meeting,day,rn,ymd=m.groups()
    expect_v=VENUE_CODE.get(str(row.get('venue') or ''))
    if ymd!=str(row.get('raceDate') or '').replace('-',''):return False,'DATE_MISMATCH'
    if int(rn)!=int(row.get('raceNo') or 0):return False,'RACE_NO_MISMATCH'
    if expect_v and vc!=expect_v:return False,'VENUE_MISMATCH'
    return True,None

def verified_result_url(bundle):
    race=bundle['race'];date=str(race.get('raceDate') or '');venue=str(race.get('venue') or '');rn=int(race.get('raceNo') or 0);prov=bundle.get('provenance') or {}
    for result_url in (str(prov.get('resultUrl') or ''),str(race.get('resultUrl') or '')):
        m=RESULT_RE.search(urllib.parse.unquote(result_url)) if result_url else None
        if groups_match(m,date,venue,rn):return result_url,'history_result_identity_verified'
    for entry_url in (str(prov.get('entryUrl') or ''),str(race.get('entryUrl') or '')):
        em=ENTRY_RE.search(urllib.parse.unquote(entry_url)) if entry_url else None
        if not groups_match(em,date,venue,rn):continue
        parsed=urllib.parse.urlparse(entry_url);qs=urllib.parse.parse_qs(parsed.query);cname=urllib.parse.unquote(qs.get('CNAME',[''])[0])
        if not cname or '01dde' not in cname:continue
        result_cname=cname.replace('01dde','01sde',1)
        result='https://www.jra.go.jp/JRADB/accessS.html?CNAME='+urllib.parse.quote(result_cname,safe='')
        rm=RESULT_RE.search(urllib.parse.unquote(result))
        if not groups_match(rm,date,venue,rn):raise RuntimeError(f'DERIVED_RESULT_IDENTITY_FAILED:{race.get("raceId")}:{result}')
        return result,'validated_current_direct_desktop'
    raise RuntimeError(f'NO_VERIFIED_RESULT_OR_ENTRY_URL:{race.get("raceId")}')

def load_odds_dir(path,patterns):
    out={}
    if not path:return out
    for pat in patterns:
        for p in sorted(Path(path).glob(pat)):
            for r in read_jsonl(p):out[str(r['raceId'])]=r
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--selection',required=True);ap.add_argument('--history',required=True);ap.add_argument('--continuous-odds-dir',required=True);ap.add_argument('--canonical-odds-dir',required=True);ap.add_argument('--additional-odds-dir');ap.add_argument('--predictions-dir',required=True);ap.add_argument('--reused-out',required=True);ap.add_argument('--missing-out',required=True);ap.add_argument('--history-out',required=True);ap.add_argument('--predictions-out',required=True);ap.add_argument('--meta',required=True);a=ap.parse_args()
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
    additional=load_odds_dir(a.additional_odds_dir,['research-meta-market-odds-20*.jsonl','research-continuous-market-odds-20*.jsonl']) if a.additional_odds_dir else {}
    reused={};source_by_rid={};rejected=[]
    def accept(source_name,rid,r,strict=False):
        ok,reason=identity_ok(r)
        if not ok:
            if strict:raise RuntimeError(f'{source_name}_IDENTITY_REGRESSION:{rid}:{reason}')
            rejected.append({'raceId':rid,'source':source_name,'reason':reason});return
        if not (r.get('officialOdds') or {}).get('win'):
            if strict:raise RuntimeError(f'{source_name}_WIN_MISSING:{rid}')
            rejected.append({'raceId':rid,'source':source_name,'reason':'WIN_ODDS_MISSING'});return
        reused[rid]=r;source_by_rid[rid]=source_name
    for rid in selected:
        r=canonical.get(rid)
        if r:accept('canonical297',rid,r,False)
    for rid in selected:
        r=continuous.get(rid)
        if r:accept('continuousSourceClean',rid,r,True)
    for rid in selected:
        r=additional.get(rid)
        if r:accept('additionalSourceClean',rid,r,True)
    source_counts=collections.Counter(source_by_rid.values())
    missing=[];resolution_counts=collections.Counter()
    for rid in sorted(set(selected)-set(reused),key=lambda x:(selected[x]['raceDate'],x)):
        bundle=hist[rid];race=bundle['race'];url,method=verified_result_url(bundle);resolution_counts[method]+=1
        missing.append({'raceId':rid,'raceDate':str(race['raceDate']),'venue':str(race['venue']),'raceNo':int(race['raceNo']),'entryUrl':race.get('entryUrl') or (bundle.get('provenance') or {}).get('entryUrl'),'resultUrl':url,'requiredMarkets':list(MARKETS),'resultUrlResolutionMethod':method,'targetDayResultsUsedForSelection':False,'syntheticOddsUsed':False,'productionDatabaseWritten':False})
    reused_rows=[reused[rid] for rid in sorted(reused,key=lambda x:(selected[x]['raceDate'],x))]
    selected_hist=[hist[rid] for rid in sorted(selected,key=lambda x:(selected[x]['raceDate'],x))]
    selected_pred=[r for rid in sorted(pred,key=lambda x:(selected[x]['raceDate'],x)) for r in pred[rid]]
    write_jsonl(a.reused_out,reused_rows);write_jsonl(a.missing_out,missing);write_jsonl(a.history_out,selected_hist);write_jsonl(a.predictions_out,selected_pred)
    by_year=collections.Counter(r['raceDate'][:4] for r in missing)
    meta={'purpose':'research_only_audited_meta_market_input','selectedRaces':14410,'reusedOddsRaces':len(reused),'missingOddsRaces':len(missing),'reusedSourceCounts':dict(source_counts),'missingByYear':dict(sorted(by_year.items())),'rejectedReuseRows':rejected,'missingUrlResolutionCounts':dict(resolution_counts),'additionalSourceCleanConfigured':bool(a.additional_odds_dir),'allMissingResultUrlsIdentityVerified':True,'allMissingRequiredMarkets':list(MARKETS),'selectedPredictionRaces':len(pred),'selectedPredictionRows':len(selected_pred),'selectedHistoryRaces':len(selected_hist),'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False}
    Path(a.meta).parent.mkdir(parents=True,exist_ok=True);Path(a.meta).write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(meta,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
