#!/usr/bin/env python3
"""Restore the exact 716.827267% retrospective allocator; never claim OOF ROI.

Source: dcb1c55900dcc95d0ada22af7dbbd772d9b86fc2
Uses frozen original candidate tickets, not independently generated selections.
"""
import base64,bisect,collections,gzip,json,math,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1]
OUT=R/"src/v1/frozen-716-cash-prior-2026.json"
B=(0,1.5,2.5,4,6,10,16,25,40,65,100,200,400,800,1600,5000,1e18)
T=("単勝","ワイド","馬連","馬単","3連複","3連単")
def load():
    chunks=sorted((R/"src/v1/ten-year-history-data").glob("bin-*.ts"))
    assert len(chunks)==9
    encoded="".join(json.loads(p.read_text(encoding="utf8").strip()[len("export default "):].rstrip(";")) for p in chunks)
    data=json.loads(gzip.decompress(base64.b64decode(encoded)))
    assert (data["start"],data["end"],len(data["races"]))==("2016-08-10","2026-08-09",34566)
    rows=[]
    for x in data["races"]:
        if x[8] is None:continue
        assert len(x[8])==2 and x[8][0][0]!=x[8][1][0]
        tickets=[]
        for bt,combo,odds,ret in x[8]:
            assert bt in T and math.isfinite(float(odds)) and float(odds)>0
            tickets.append((bt,bisect.bisect_right(B,float(odds))-1,int(ret)))
        rows.append((str(x[0]),str(x[1]),int(str(x[1])[:4]),str(x[2]),int(x[3]),tickets))
    assert len(rows)==14410
    assert sum(t[2] for r in rows for t in r[5])==124401700
    byday=collections.Counter((r[1],r[3]) for r in rows)
    assert len(byday)==2882 and all(v==5 for v in byday.values())
    return rows
def key(bt,ob,rn):
    return json.dumps([bt,ob,rn],ensure_ascii=False,separators=(",",":"))
def fit(rows,year):
    markets=collections.defaultdict(lambda:[0,0])
    cells=collections.defaultdict(lambda:[0,0])
    for r in rows:
        if r[2]>=year:continue
        for bt,ob,ret in r[5]:
            cash=min(ret,30000)
            m=markets[bt];m[0]+=1;m[1]+=cash
            c=cells[key(bt,ob,r[4])];c[0]+=1;c[1]+=cash
    return {"markets":dict(markets),"cells":dict(cells)}
def estimate(r,t,stats):
    bt,ob,_=t
    n,p=stats["markets"].get(bt,(0,0))
    known=p/(1000*n) if n else .8
    size,cash=stats["cells"].get(key(bt,ob,r[4]),(0,0))
    return max(.01,(cash/1000+40*known)/(size+40))
def evaluate(rows,year,stats):
    days=collections.defaultdict(list)
    for r in rows:
        if r[2]!=year:continue
        a,b=(estimate(r,t,stats) for t in r[5])
        share=a**4/(a**4+b**4)
        stake_a=100*max(1,min(19,round(share*20)))
        paid=(r[5][0][2]*stake_a+r[5][1][2]*(2000-stake_a))//1000
        days[(r[1],r[3])].append((-(a+b),r[0],paid))
    return [x for d in days.values() for x in sorted(d)[:3]]
def generate():
    rows=load()
    all_bets=[]
    expected={2023:12431290,2024:11704110,2025:12194730,2026:8571930}
    for yr in expected:
        bets=evaluate(rows,yr,fit(rows,yr))
        assert sum(b[2] for b in bets)==expected[yr],(yr,sum(b[2] for b in bets))
        all_bets+=bets
    n=len(all_bets);paid=sum(b[2] for b in all_bets);largest=max(b[2] for b in all_bets)
    assert (n,paid,largest)==(3132,44902060,737580)
    stats=fit(rows,2026)
    out=dict(schema="source-faithful-716-cash-2026-v1",
      sourceCommit="dcb1c55900dcc95d0ada22af7dbbd772d9b86fc2",
      targetYear=2026,latestTrainingYear=2025,sourceArchiveEnd="2026-08-09",
      sourceSelectedRaces=14410,
      recipe=dict(regime=["market","odds","raceNo"],capYen=30000,priorTickets=40,
        stakePower=4,racesPerVenueDay=3,raceRankMode="both",stakePerRaceYen=2000),
      historicalResearchRoiPct=716.827267,historicalResearchMinusMaxRaceRoiPct=705.052363,
      historicalAudit=dict(races=n,stakeYen=n*2000,paidYen=paid,largestRacePaidYen=largest),
      researchOnly=True,sourceGeneratorLookaheadRisk=True,
      prospectiveRoiUnverified=True,**stats)
    return json.dumps(out,ensure_ascii=False,separators=(",",":"),sort_keys=True)+"\n"
if __name__=="__main__":
    text=generate()
    if "--check" in sys.argv:
        assert OUT.exists() and OUT.read_text(encoding="utf8")==text,"PRIOR_MISSING_OR_CHANGED"
    else:
        OUT.write_text(text,encoding="utf8")
    print("SOURCE_FAITHFUL_716827_CASH_PARITY_OK",len(text))
