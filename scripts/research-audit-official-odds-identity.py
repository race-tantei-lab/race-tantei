#!/usr/bin/env python3
import argparse, json, re, urllib.parse
from pathlib import Path

VENUE_CODE = {
    '札幌':'01','函館':'02','福島':'03','新潟':'04','東京':'05',
    '中山':'06','中京':'07','京都':'08','阪神':'09','小倉':'10',
}
RESULT_RE = re.compile(
    r'^(?:pw|sw)01sde(?:01|10)(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})(?:/([0-9A-Fa-f]{2}))?$'
)
ODDS_RE = re.compile(
    r'^(?:pw|sw)15[1-8]ou(?:01|10)(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})(?:Z)?(?:/([0-9A-Fa-f]{2}))?$'
)


def cname(url):
    try:
        q=urllib.parse.parse_qs(urllib.parse.urlparse(str(url or '')).query)
        return urllib.parse.unquote((q.get('CNAME') or q.get('cname') or [''])[0])
    except Exception:
        return ''


def expected(row):
    date=str(row.get('raceDate') or '')
    venue=str(row.get('venue') or '')
    no=int(row.get('raceNo') or 0)
    vc=VENUE_CODE.get(venue)
    if not vc or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date) or not (1<=no<=12):
        raise RuntimeError(f'ROW_IDENTITY_INVALID:{row.get("raceId")}:{date}:{venue}:{no}')
    return vc,date[:4],f'{no:02d}',date.replace('-','')


def parse_identity(raw, pattern):
    m=pattern.match(str(raw or ''))
    if not m:
        return None
    venue,year,_meeting,_day,race_no,ymd,*_=m.groups()
    return venue,year,race_no,ymd


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--odds-dir',required=True)
    ap.add_argument('--out',required=True)
    args=ap.parse_args()
    files=sorted(Path(args.odds_dir).glob('research-continuous-market-odds-20*.jsonl'))
    rows=[]
    for p in files:
        for line in p.read_text(encoding='utf-8').splitlines():
            if line.strip(): rows.append(json.loads(line))
    by_id={}
    duplicate=[]
    for r in rows:
        rid=str(r.get('raceId') or '')
        if rid in by_id: duplicate.append(rid)
        by_id[rid]=r
    mismatches=[]; unparsable=[]; source_mismatches=[]; horse_mismatches=[]
    source_counts={}
    for rid,r in sorted(by_id.items()):
        want=expected(r)
        prov=r.get('provenance') or {}
        src=str(prov.get('officialOddsSource') or 'unknown')
        source_counts[src]=source_counts.get(src,0)+1
        ru=str(prov.get('resultUrl') or '')
        raw=cname(ru)
        got=parse_identity(raw,RESULT_RE)
        if got is None:
            unparsable.append({'raceId':rid,'raceDate':r.get('raceDate'),'venue':r.get('venue'),'raceNo':r.get('raceNo'),'resultUrl':ru,'cname':raw,'source':src})
        elif got!=want:
            mismatches.append({'raceId':rid,'raceDate':r.get('raceDate'),'venue':r.get('venue'),'raceNo':r.get('raceNo'),'expected':want,'actual':got,'resultUrl':ru,'source':src})
        sc=prov.get('sourceCnames') or {}
        for market,rawc in sc.items():
            ogot=parse_identity(str(rawc),ODDS_RE)
            if ogot is None or ogot!=want:
                source_mismatches.append({'raceId':rid,'market':market,'expected':want,'actual':ogot,'sourceCname':rawc,'source':src})
        horses=sorted(int(x) for x in (r.get('horses') or []))
        win=r.get('officialOdds',{}).get('win') or {}
        active=sorted(int(k) for k,v in win.items() if v is not None)
        if horses!=active:
            horse_mismatches.append({'raceId':rid,'horses':horses,'activeWinOddsHorses':active,'source':src})
    result={
        'purpose':'research_only_official_odds_identity_audit',
        'files':len(files),'rows':len(rows),'uniqueRaceIds':len(by_id),
        'duplicateRaceIds':sorted(set(duplicate)),
        'resultUrlMismatchCount':len(mismatches),'resultUrlMismatches':mismatches,
        'resultUrlUnparsableCount':len(unparsable),'resultUrlUnparsable':unparsable,
        'sourceCnameMismatchCount':len(source_mismatches),'sourceCnameMismatches':source_mismatches,
        'horseSetMismatchCount':len(horse_mismatches),'horseSetMismatches':horse_mismatches,
        'sourceCounts':source_counts,
        'syntheticOddsUsed':False,'productionDatabaseWritten':False,'productionModelChanged':False,
    }
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('rows','uniqueRaceIds','resultUrlMismatchCount','resultUrlUnparsableCount','sourceCnameMismatchCount','horseSetMismatchCount')},ensure_ascii=False))
    if duplicate: raise RuntimeError(f'DUPLICATE_RACE_IDS:{len(set(duplicate))}')

if __name__=='__main__': main()
