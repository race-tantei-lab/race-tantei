#!/usr/bin/env python3
"""Fail-closed cash settlement and coverage audit for research-only backtests."""
import csv, gzip, json, sys
from collections import defaultdict
from pathlib import Path

def audit(path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        rows=list(csv.DictReader(f))
    if not rows: raise ValueError("EMPTY_BET_LEDGER")
    seen=set(); days=defaultdict(list); years=defaultdict(list)
    for r in rows:
        key=(r["year"],r["day"],r["venue"],r["raceId"])
        if key in seen: raise ValueError("DUPLICATE_RACE:"+str(key))
        seen.add(key)
        if r["marketA"]==r["marketB"]: raise ValueError("SAME_MARKET:"+str(key))
        if not r["ticketA"].isdigit() or not r["ticketB"].isdigit(): raise ValueError("INVALID_TICKET")
        if int(r["stakeYen"])!=200: raise ValueError("INVALID_STAKE")
        paid=int(r["paidYen"])
        if paid<0 or paid%10: raise ValueError("INVALID_PAYMENT")
        days[(r["day"],r["venue"])].append(r)
        years[r["year"]].append(r)
    if any(len(v)>5 for v in days.values()): raise ValueError("MORE_THAN_FIVE_RACES")
    def metrics(rs):
        stake=sum(int(x["stakeYen"]) for x in rs)
        paid=sum(int(x["paidYen"]) for x in rs)
        biggest=max((int(x["paidYen"]) for x in rs),default=0)
        return dict(races=len(rs),stakeYen=stake,paidYen=paid,
                    roiPct=100*paid/stake if stake else None,
                    minusMaxPayoutRaceRoiPct=100*(paid-biggest)/stake if stake else None,
                    hitRaces=sum(int(x["paidYen"])>0 for x in rs))
    return dict(total=metrics(rows),years={y:metrics(rs) for y,rs in sorted(years.items())},
                observedVenueDays=len(days),
                observedDaysWith3To5=sum(3<=len(v)<=5 for v in days.values()),
                observedDaysWith5=sum(len(v)==5 for v in days.values()),
                IMPORTANT="Observed venue-days exclude dates with zero selected races; denominator requires independent JRA program calendar. No official T-15 or JRA payout verification.")
def main():
    if "--self-test" in sys.argv:
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"bets.csv.gz"
            with gzip.open(p,"wt",encoding="utf-8",newline="") as f:
                w=csv.DictWriter(f,fieldnames=["year","day","venue","raceId","marketA","marketB","ticketA","ticketB","stakeYen","paidYen"])
                w.writeheader()
                for i,pay in enumerate((500,100),1):
                    w.writerow(dict(year="2023",day="2023-01-01",venue="01",raceId=str(i),marketA="単勝",marketB="馬連",ticketA="0",ticketB="7",stakeYen=200,paidYen=pay))
            x=audit(p)
            assert x["total"]["roiPct"]==150
            assert x["total"]["minusMaxPayoutRaceRoiPct"]==25
        print("CASH_AUDIT_SELF_TEST_OK")
    else:
        print(json.dumps(audit(Path(sys.argv[1])),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
