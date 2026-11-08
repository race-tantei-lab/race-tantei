#!/usr/bin/env python3
"""Research-only pre-result ticket selection and stringent JRA settlement audit.

No post-race payout may enter select_plan. Requires immutable pre-race score rows.
The max single-ticket and max single-race payout are removed independently
while ALL original stakes remain in the denominator. Never claim T-15 provenance.
"""
from __future__ import annotations
from collections import defaultdict
from itertools import combinations
import math

MARKETS = ("単勝", "ワイド", "馬連", "馬単", "3連複", "3連単")

def select_plan(races, stake_per_race=2000, min_stake=100):
    """races: dict race_id -> list of {market, selection, expected_return, race_score}.
    Pure pre-result selection; 5 races and 2 different markets per race.
    Uses conservative EV utility; no result, payout, or finishing position inputs.
    """
    if stake_per_race % min_stake or stake_per_race < 2*min_stake:
        raise ValueError("INVALID_STAKE")
    if len(races) < 5:
        raise ValueError("INSUFFICIENT_RACES")
    candidates=[]
    for rid, tickets in races.items():
        best={}
        for t in tickets:
            market=t["market"]
            if market not in MARKETS: raise ValueError("INVALID_MARKET")
            ev=float(t["expected_return"])
            if not math.isfinite(ev) or ev < 0: raise ValueError("INVALID_EXPECTATION")
            if market not in best or ev > best[market]["expected_return"]:
                best[market]={"market":market,"selection":t["selection"],"expected_return":ev}
        if len(best)<2:continue
        pairs=list(combinations(best.values(),2))
        # Keep a fixed risk budget, allocate 100-yen units by EV advantage.
        scored=[]
        units=stake_per_race//min_stake
        for a,b in pairs:
            for k in range(1,units):
                utility=(k*a["expected_return"]+(units-k)*b["expected_return"])/units
                # concentration penalty independent of realized payout
                utility-=.12*((k/units)**2+((units-k)/units)**2)
                scored.append((utility,k,a,b))
        score,k,a,b=max(scored,key=lambda x:x[0])
        candidates.append((score,str(rid),[
            {"market":a["market"],"selection":a["selection"],"stake":k*min_stake},
            {"market":b["market"],"selection":b["selection"],"stake":(units-k)*min_stake}
        ]))
    if len(candidates)<5:raise ValueError("INSUFFICIENT_VALID_RACES")
    chosen=sorted(candidates,key=lambda x:(-x[0],x[1]))[:5]
    return {rid: tickets for _,rid,tickets in chosen}

def audit(plan, settled, stake_per_race=2000):
    """settled[(race_id,market,selection)] = actual JRA payout yen for stake.
    Missing settlement is an error, never silently assumed a losing ticket.
    """
    if len(plan)!=5:raise ValueError("NOT_FIVE_RACES")
    total=0; returned=0; hits=0; ticket_payouts=[]; race_payouts=[]
    for rid, tickets in plan.items():
        if len(tickets)!=2 or len({t["market"] for t in tickets})!=2:
            raise ValueError("NOT_TWO_DIFFERENT_MARKETS")
        stakes=sum(t["stake"] for t in tickets)
        if stakes!=stake_per_race:raise ValueError("BUDGET_MISMATCH")
        total+=stakes; race_paid=0
        for t in tickets:
            key=(rid,t["market"],t["selection"])
            if key not in settled:raise ValueError("MISSING_JRA_SETTLEMENT")
            amount=settled[key]
            if not isinstance(amount,int) or amount<0:raise ValueError("INVALID_PAYOUT")
            race_paid+=amount;ticket_payouts.append(amount)
        hits+=int(race_paid>0);returned+=race_paid;race_payouts.append(race_paid)
    assert total==5*stake_per_race
    return {"races":5,"hit_races":hits,"hit_rate":hits/5,
            "stake":total,"payout":returned,"profit":returned-total,
            "roi":returned/total,
            "roi_without_max_ticket":(returned-max(ticket_payouts))/total,
            "roi_without_max_race":(returned-max(race_payouts))/total,
            "passes_robust200":hits>=1 and returned>=2*total
               and returned-max(ticket_payouts)>=2*total
               and returned-max(race_payouts)>=2*total}

def self_test():
    races={f"r{i}":[{"market":m,"selection":f"{i}-{m}",
                       "expected_return":1.1+(i%7)*.03+j*.04}
                      for j,m in enumerate(MARKETS)] for i in range(7)}
    plan=select_plan(races)
    assert len(plan)==5 and all(sum(t["stake"] for t in ts)==2000 for ts in plan.values())
    settled={(rid,t["market"],t["selection"]):3000 for rid,ts in plan.items() for t in ts}
    a=audit(plan,settled)
    assert a["stake"]==10000 and a["payout"]==30000
    assert a["roi_without_max_ticket"]==2.7
    assert a["roi_without_max_race"]==2.4 and a["passes_robust200"]
    # The same total ROI can be jackpot-dependent and must fail.
    keys=list(settled)
    settled={k:(30000 if k==keys[0] else 0) for k in keys}
    b=audit(plan,settled)
    assert b["roi"]==3 and b["roi_without_max_ticket"]==0
    assert b["roi_without_max_race"]==0 and not b["passes_robust200"]
    try:audit(plan,{})
    except ValueError as e:assert str(e)=="MISSING_JRA_SETTLEMENT"
    else:raise AssertionError("missing payout accepted")
    print("ROBUST200_TICKET_RACE_FIXED_DENOMINATOR_OK")

if __name__=="__main__":self_test()
