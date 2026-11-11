#!/usr/bin/env python3
"""Seasonal MULTI-CONDITION betting policy, evaluated in paid JPY.

NOT 1 model = 1 condition. Construct ONE rule-set with condition switches
selected by historical season (quarter) and optionally market. A rule is a
previously discovered robust-200 cash cell. Freeze all seasonal memberships
and weights using 2017-2022 only; then make chronological 2023-2026 bets.

Each hypothetical race gets no more than two independently scored tickets,
from two distinct real JRA bet markets. Per venue/program-day, select up to
five eligible races before looking up result payouts. Report all spent/paid
yen by year, quarter, venue-day, and max-paying race removed; report missing
5R coverage as a FAIL, never silently drop failing days.

This is retrospective RESEARCH. Archived odds are final win odds, not JRA
official T-15. Settlements are third-party mirrored 100-JPY payouts, not
independently JRA verified. Future/live 200% ROI is NOT established.
"""
from __future__ import annotations

from collections import Counter,defaultdict
from pathlib import Path
import csv,gzip,importlib.util,json,math,sys,time
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-seasonal-ensemble-actual-cash.json"
PER_RACE=ROOT/"analysis-results/nov2026-seasonal-ensemble-frozen-bets.csv.gz"
INPUTS=(
 ROOT/"analysis-results/premined-form/nov2026-form-decade-all-robust-cells.csv.gz",
 ROOT/"analysis-results/premined-joint/nov2026-relative-draw-robust-cells.csv.gz",
)
TRAIN_YEARS=tuple(range(2017,2023))
CHECK_YEARS=(2023,2024,2025,2026)
POLICIES=(
    ("seasonal_top12",12,4),
    ("seasonal_top24",24,8),
    ("seasonal_top48",48,12),
    ("seasonal_all_robust",999,999),
)
MIN_SEASON_TICKETS=20
MIN_SEASON_PAID_TICKETS=2
MIN_SEASON_MINUS_MAX_PCT=200.0
MARKETS=("単勝","ワイド","馬連","馬単","3連複","3連単")

def mod(filename,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/filename)
    if spec is None or spec.loader is None:
        raise RuntimeError("MISSING_RESEARCH_DEPENDENCY:"+filename)
    obj=importlib.util.module_from_spec(spec)
    sys.modules[name]=obj
    spec.loader.exec_module(obj)
    return obj

def max_race(paid,race_id):
    keep=paid>0
    if not np.any(keep):return 0.0
    return float(np.bincount(race_id[keep],weights=paid[keep]).max())

def percent(paid,tickets):
    return round(float(paid)/float(tickets),4) if tickets else None

def cash_metrics(picks):
    stake=200*len(picks)
    ret=sum(x["paidYen"] for x in picks)
    best=max([x["paidYen"] for x in picks],default=0)
    hit=sum(x["paidYen"]>0 for x in picks)
    return {"races":len(picks),"bets":2*len(picks),
            "stakeYen":stake,"paidYen":ret,"profitYen":ret-stake,
            "roiPct":round(100*ret/stake,4) if stake else None,
            "maxOneRacePayoutYen":best,
            "minusMaxRaceRoiPct":round(100*(ret-best)/stake,4) if stake else None,
            "hitRaces":hit,"hitRacePct":round(100*hit/len(picks),4) if picks else None}

def load_premine():
    seen=set()
    result=[]
    for path in INPUTS:
        if not path.exists():raise RuntimeError("DISCOVERY_ARTIFACT_MISSING:"+str(path))
        with gzip.open(path,"rt",encoding="utf-8") as fh:
            for item in csv.DictReader(fh):
                fields=tuple(item["schema"].split("+"))
                key=(fields,int(item["conditionCode"]))
                if key in seen:continue
                seen.add(key)
                if float(item["trainMinusMaxRaceRoiPct"])<200:
                    raise RuntimeError("UNPROFITABLE_DISCOVERY_CANDIDATE")
                result.append({
                    "fields":fields,
                    "code":int(item["conditionCode"]),
                    "market":item["market"],
                    "n":int(item["trainTickets"]),
                    "paid":int(item["trainPaidYen"]),
                    "minusMaxRoi":float(item["trainMinusMaxRaceRoiPct"])})
    if not 100<=len(result)<=150:
        raise RuntimeError("DISCOVERY_RULES_NOT_EXPECTED_100_150:"+str(len(result)))
    return result

def obtain_rows():
    source=mod("scripts/research-nov2026-decade-roi-first-sixmarkets.py","seasonal_source")
    parser=mod("scripts/research-nov2026-sixmarket-real-paid-cash.py","seasonal_parser")
    form=mod("scripts/research-nov2026-chronological-form-money-conditions.py","seasonal_form")
    hist=mod("scripts/research-nov2026-56feature-sixmarket-pl-money.py","seasonal_historical")
    direct=mod("scripts/research-nov2026-form-direct-cash-failclosed.py","seasonal_joins")
    joint=mod("scripts/research-nov2026-relative-draw-cash.py","seasonal_mixed")
    archive=source.read_all_races(parser.parse_payments)
    if not (source.CACHE.exists() and source.RACE_CACHE.exists()):
        source.CACHE.parent.mkdir(parents=True,exist_ok=True)
        source.full_features(archive)
    recorded=json.loads(source.RACE_CACHE.read_text(encoding="utf-8"))["races"]
    if len(archive)!=len(recorded) or any(r["id"]!=z["id"] for r,z in zip(archive,recorded)):
        raise RuntimeError("CASH_RACE_ORDER_MISMATCH")
    for r in archive:
        r["no"]=r["raceNo"]
        r["venue"]=f"{int(r['venue']):02d}"
    identity=joint.names_from_monthly_data(
        sorted(source.FILES.glob("raceresults_*.csv")),hist)
    x,winners,offsets,metadata,horse_names,_=hist.historical_horse_features()
    eligible=[r for r in archive if r["month"]>="201701"]
    matches,join_counts=direct.joined_full_names(
        eligible,metadata,horse_names,identity,hist)
    rr=np.asarray([i for i,r in enumerate(archive)
                   if r["month"]>="201701" and r["id"] in matches],dtype=np.int32)
    races=[archive[int(i)] for i in rr]
    yearly=Counter(int(r["month"][:4]) for r in races)
    if len(races)<16000 or any(yearly[y]<500 for y in (*TRAIN_YEARS,*CHECK_YEARS)):
        raise RuntimeError("INSUFFICIENT_YEARWISE_HISTORICAL_MATCHES")
    formvals=form.form_categories(races,matches,metadata,offsets,x)
    columns=("rankMin","rankMax","rankGap","oddsGeom","favOdds",
             "venue","fieldSize","quarter","draw","horseAge")
    template=joint.rank7_market_indices(source,form)
    with np.load(source.CACHE,allow_pickle=False) as z:
        if z["payout"].shape!=(len(archive),1030):raise RuntimeError("PAYOUT_CASH_DIMENSION")
        cash=z["payout"][rr[:,None],template[None,:]].astype(np.int32).ravel()
        cats={k:z[k][rr[:,None],template[None,:]].astype(np.uint8).ravel()
              for k in columns}
    cat={**cats,**formvals}
    field_width=source.SINGLE_BINS["fieldSize"]
    cat["relativeDraw"]=(cats["draw"].astype(np.int32)*field_width+
                         cats["fieldSize"].astype(np.int32)).astype(np.uint8)
    widths={**{k:4 for k in form.NEW_NAMES},
            **{k:source.SINGLE_BINS[k] for k in columns},
            "relativeDraw":source.SINGLE_BINS["draw"]*field_width}
    if any(len(v)!=len(cash) for v in cat.values()):
        raise RuntimeError("NOT_ALL_CASH_TICKETS_HAVE_PRIOR_FORM")
    types=np.tile(np.array([0]*7+[1]*21+[2]*21+[3]*42+[4]*35+[5]*210,dtype=np.uint8),len(races))
    rid=np.repeat(np.arange(len(races),dtype=np.int32),336)
    year=np.asarray([int(r["month"][:4]) for r in races])
    quarter=np.asarray([(int(r["month"][4:])-1)//3+1 for r in races],dtype=np.uint8)
    print("SEASONAL_CASH_DATASET",json.dumps({
       "matchedRaces":len(races),"years":dict(yearly),
       "tickets":len(cash),"joinCounts":join_counts,
       "officialT15Odds":False},ensure_ascii=False),flush=True)
    return races,cash,cat,widths,types,rid,year,quarter,joint

def discover_quarter_memberships(rules,data):
    races,cash,cat,widths,types,rid,year,quarter,joint=data
    yrow=year[rid]
    qrow=quarter[rid]
    train=np.isin(yrow,TRAIN_YEARS)
    if not np.any(train):raise RuntimeError("TRAIN_EMPTY")
    members={q:[] for q in range(1,5)}
    matches=[]
    code_cache={}
    for i,rule in enumerate(rules):
        fields=rule["fields"]
        if fields not in code_cache:
            code_cache[fields]=joint.mixed(types,cat,widths,fields)[0]
        mask=(code_cache[fields]==rule["code"])
        if int(np.count_nonzero(mask&train))!=rule["n"]:
            raise RuntimeError("TRAIN_RULE_TICKET_RECONCILIATION_FAIL:"+str((i,fields,rule["n"],int(np.count_nonzero(mask&train)))))
        if int(cash[mask&train].sum(dtype=np.int64))!=rule["paid"]:
            raise RuntimeError("TRAIN_RULE_CASH_RECONCILIATION_FAIL:"+str(i))
        matches.append(np.flatnonzero(mask).astype(np.int32))
        for q in range(1,5):
            inside=mask&train&(qrow==q)
            n=int(inside.sum())
            if n<MIN_SEASON_TICKETS:continue
            winner_count=int(np.count_nonzero(cash[inside]))
            if winner_count<MIN_SEASON_PAID_TICKETS:continue
            pay=int(cash[inside].sum(dtype=np.int64))
            largest=max_race(cash[inside],rid[inside])
            robust=percent(pay-largest,n)
            if robust is None or robust<MIN_SEASON_MINUS_MAX_PCT:continue
            # Strength weights capped so a single jackpot does not dominate
            # voting. Entire score is determined using training YEARS only.
            strength=math.log1p(n)*min(robust/200.,2.)
            members[q].append({
              "index":i,"market":rule["market"],"quarter":q,
              "stakeYen":100*n,"paidYen":pay,"cashRoiPct":percent(pay,n),
              "maxRacePaidYen":int(largest),"minusMaxRaceRoiPct":robust,
              "trainTickets":n,"trainPaidTickets":winner_count,
              "voteWeight":round(strength,6),
              "fields":"+".join(fields),"code":rule["code"]})
    for q in range(1,5):
        members[q].sort(key=lambda v:(-v["voteWeight"],-v["trainTickets"],v["index"]))
    print("SEASONAL_CASH_RULES",json.dumps({
        "allHistoricalRobustRules":len(rules),
        "seasonallyRobustRules":{str(q):len(members[q]) for q in range(1,5)},
        "seasonlyMarkets":{str(q):dict(Counter(x["market"] for x in members[q])) for q in range(1,5)}
    },ensure_ascii=False),flush=True)
    return members,matches

def freeze_rules(members,policy):
    name,maxrules,maxmarket=policy
    result={}
    for q in range(1,5):
        count=Counter()
        eligible=[]
        for r in members[q]:
            if len(eligible)>=maxrules:break
            if count[r["market"]]>=maxmarket:continue
            eligible.append(r)
            count[r["market"]]+=1
        result[q]=eligible
    return result

def bets_from_frozen_rules(ruleset,match_indices,data,policy):
    races,cash,cat,widths,types,rid,year,quarter,joint=data
    votes=np.zeros(len(cash),dtype=np.float32)
    for q,rows in ruleset.items():
        for row in rows:
            idx=match_indices[row["index"]]
            qmask=(quarter[rid[idx]]==q)
            votes[idx[qmask]]+=row["voteWeight"]
    race_choices=[]
    for i,r in enumerate(races):
        first=i*336
        scores=votes[first:first+336]
        if not np.any(scores>0):continue
        choices=[]
        market_offsets=((0,7),(7,28),(28,49),(49,91),(91,126),(126,336))
        for market,(lo,hi) in enumerate(market_offsets):
            m=scores[lo:hi]
            if np.any(m>0):
                local=int(np.argmax(m))
                choices.append((float(m[local]),market,first+lo+local))
        if len(choices)<2:continue
        chosen=sorted(choices,key=lambda z:(-z[0],z[1],z[2]))[:2]
        assert chosen[0][1]!=chosen[1][1]
        pos=[z[2] for z in chosen]
        totalpay=int(cash[pos].sum(dtype=np.int64))
        race_choices.append({
           "raceIndex":i,"raceId":r["id"],"day":r["day"],
           "venue":r["venue"],"month":r["month"],
           "year":int(r["month"][:4]),
           "quarter":int(quarter[i]),"rankScore":round(sum(z[0] for z in chosen),5),
           "market1":MARKETS[chosen[0][1]],"market2":MARKETS[chosen[1][1]],
           "ticket1":pos[0]-first,"ticket2":pos[1]-first,
           "paidYen":totalpay,"payout1Yen":int(cash[pos[0]]),
           "payout2Yen":int(cash[pos[1]])})
    # ONLY PRE-RACE votes and race metadata determine the selected races.
    by_day=defaultdict(list)
    for r in race_choices:by_day[(r["day"],r["venue"])].append(r)
    chosen=[]
    coverage=Counter()
    all_program_days=defaultdict(list)
    for i,r in enumerate(races):
        all_program_days[(r["day"],r["venue"])].append(i)
    for key,values in by_day.items():
        values.sort(key=lambda x:(-x["rankScore"],x["raceId"]))
        selected=values[:5]
        chosen.extend(selected)
        coverage["eligibleProgramDays"]+=1
        coverage["days5EligibleRaces"]+=int(len(values)>=5)
        coverage["days3EligibleRaces"]+=int(len(values)>=3)
    coverage["allProgramDays"]=len(all_program_days)
    coverage["daysUnder3Eligible"]=len(all_program_days)-coverage["days3EligibleRaces"]
    coverage["daysUnder5Eligible"]=len(all_program_days)-coverage["days5EligibleRaces"]
    coverage["eligibleCandidateRaces"]=len(race_choices)
    coverage["boughtRaces"]=len(chosen)
    if any(x["market1"]==x["market2"] for x in chosen):raise RuntimeError("SAME_BET_MARKET_ON_RACE")
    if len({x["raceId"] for x in chosen})!=len(chosen):
        raise RuntimeError("DUPLICATE_RACE_SELECTED")
    return chosen,dict(coverage)

def summarize_periods(chosen,coverage):
    result={}
    for y in (*TRAIN_YEARS,*CHECK_YEARS):
        sub=[r for r in chosen if r["year"]==y]
        r=cash_metrics(sub)
        r["quarters"]={str(q):cash_metrics([t for t in sub if t["quarter"]==q]) for q in range(1,5)}
        result[str(y)]=r
    forward=[r for r in chosen if r["year"] in CHECK_YEARS]
    combined=cash_metrics(forward)
    combined["includesAllUnselectedVenueDays"]=False
    # 0 bets in a season means no ROI; it is NEVER interpreted as a success.
    check={str(y):{
      "cashRoi200":(result[str(y)]["roiPct"] is not None
                     and result[str(y)]["roiPct"]>=200),
      "minusBiggestRaceCashRoi200":(result[str(y)]["minusMaxRaceRoiPct"] is not None
                      and result[str(y)]["minusMaxRaceRoiPct"]>=200),
    } for y in CHECK_YEARS}
    return {"calendarYears":result,"forwardAggregate2023To2026Apr":combined,
            "yearly200Flags":check,"coverage":coverage,
            "strictAllPeriodsPass":all(v["minusBiggestRaceCashRoi200"] for v in check.values())
                  and coverage["daysUnder3Eligible"]==0
                  and coverage["daysUnder5Eligible"]==0}

def main():
    if "--self-test" in sys.argv:
        x=[{"paidYen":300},{"paidYen":200},{"paidYen":0}]
        v=cash_metrics(x)
        assert v["stakeYen"]==600
        assert v["paidYen"]==500
        assert v["roiPct"]==round(100*500/600,4)
        assert v["minusMaxRaceRoiPct"]==round(100*200/600,4)
        assert percent(200,1)==200.
        print("SEASONAL_PORTFOLIO_CASH_SELFTEST_OK",flush=True)
        return
    start=time.monotonic()
    candidates=load_premine()
    data=obtain_rows()
    members,match_indices=discover_quarter_memberships(candidates,data)
    results={}
    best=None
    output=[]
    for policy in POLICIES:
        frozen=freeze_rules(members,policy)
        bets,coverage=bets_from_frozen_rules(frozen,match_indices,data,policy[0])
        stats=summarize_periods(bets,coverage)
        # Select policy using ONLY combined TRAINING cash and broad coverage;
        # NEVER choose a policy using 2023-26 payouts or ROI.
        train=[b for b in bets if b["year"] in TRAIN_YEARS]
        train_cash=cash_metrics(train)
        # Portfolio-selection coverage is measured on the TRAINING years
        # alone. Neither settlement nor even eligible-race counts in
        # 2023-26 may participate in selecting the portfolio variant.
        train_program_days={
            (r["day"],r["venue"]) for r in data[0]
            if int(r["month"][:4]) in TRAIN_YEARS}
        train_day_bets=Counter((b["day"],b["venue"]) for b in train)
        train_days_with_five=sum(n>=5 for n in train_day_bets.values())
        train_coverage_ratio=train_days_with_five/max(1,len(train_program_days))
        train_score=(train_cash["minusMaxRaceRoiPct"] or 0)*math.log1p(
            len(train))*(0.5+0.5*train_coverage_ratio)
        results[policy[0]]={
          "seasonRules":{str(q):[{
             k:v for k,v in rule.items() if k not in ("index",)}
             for rule in frozen[q]] for q in range(1,5)},
          "seasonRuleCounts":{str(q):len(frozen[q]) for q in range(1,5)},
          "trainingPolicy":train_cash,
          "trainingFiveRaceProgramDays":train_days_with_five,
          "trainingProgramDays":len(train_program_days),
          "trainingOnlyPolicyRankScore":round(train_score,4),
          **stats}
        print("SEASONAL_POLICY_ACTUAL_CASH",json.dumps({
           "name":policy[0],
           "training":train_cash,
           "year2023":stats["calendarYears"]["2023"],
           "year2024":stats["calendarYears"]["2024"],
           "year2025":stats["calendarYears"]["2025"],
           "year2026JanApr":stats["calendarYears"]["2026"],
           "allForward":stats["forwardAggregate2023To2026Apr"],
           "coverage":coverage},ensure_ascii=False),flush=True)
        if best is None or train_score>best[0]:
            best=(train_score,policy[0])
        for bet in bets:output.append({"policy":policy[0],**bet})
    winner=best[1]
    overall={
      "researchOnly":True,
      "notLiveProspective200Validated":True,
      "allPoliciesUsePreYearFrozenCashDerivedConditions":True,
      "training2017To2022Only":True,
      "fourSeasonConditionSwitching":True,
      "twoDistinctMarketsPerRaceWhenEligible":True,
      "fiveRaceVenueDayMaximum":True,
      "noRetroactiveBetSelectionFromRaceOutcome":True,
      "sameNamedConditionNotRequiredToWinEveryYear":True,
      "ruleCohortFromHistoricalRobust200Cells":len(candidates),
      "seasonalRulePoolByQuarter":{str(q):len(members[q]) for q in range(1,5)},
      "trainingOnlySelectedPolicy":winner,
      "policyConfigurations":results,
      "universeRaces":len(data[0]),
      "rawTicketCandidates":len(data[1]),
      "payoutSource":"third-party settled 100-yen cash, independent JRA reconciliation incomplete",
      "historicalOddsSource":"FINAL win odds, not official T-15",
      "only2026JanToAprAvailable":True,
      "noProductionOrD1Change":True,
      "seconds":round(time.monotonic()-start,2)}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(overall,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    fields=("policy","raceId","day","venue","month","year","quarter","rankScore",
        "market1","market2","ticket1","ticket2","paidYen","payout1Yen","payout2Yen")
    with gzip.open(PER_RACE,"wt",newline="",encoding="utf8") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
        w.writeheader();w.writerows(output)
    print("SEASONAL_ENSEMBLE_CASH_FINAL",json.dumps({
       "trainingSelected":winner,
       "selectedStats":{k:v for k,v in results[winner].items()
                        if k in ("calendarYears","forwardAggregate2023To2026Apr",
                                  "strictAllPeriodsPass","coverage")},
       "seconds":overall["seconds"],
       "json":str(OUT),"betsCSV":str(PER_RACE)
    },ensure_ascii=False),flush=True)

if __name__=="__main__":main()
