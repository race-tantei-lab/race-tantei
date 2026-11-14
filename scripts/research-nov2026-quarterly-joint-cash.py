#!/usr/bin/env python3
"""Quarterly prequential joint cash-regime research. Third-party settlements; NOT T-15 certified."""
import csv,gzip,importlib.util,json,sys
from pathlib import Path
from collections import defaultdict
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/nov2026-quarterly-joint-cash.json"
BETS=ROOT/"analysis-results/nov2026-quarterly-joint-cash-bets.csv.gz"
MARKETS=((0,7),(7,28),(28,49),(49,91),(91,126),(126,336))
def summarize(rows):
    stake=sum(x["stakeYen"] for x in rows);paid=sum(x["paidYen"] for x in rows)
    top=max((x["paidYen"] for x in rows),default=0)
    return dict(races=len(rows),stakeYen=stake,paidYen=paid,hitRaces=sum(x["paidYen"]>0 for x in rows),
                roiPct=round(100*paid/stake,4) if stake else None,
                minusMaxRaceRoiPct=round(100*(paid-top)/stake,4) if stake else None)
def run(races,cash,year,quarter,fields,market_state,odds_gap_state):
    n=len(races);money=cash.reshape(n,336)
    venue=np.array([str(r["venue"]) for r in races])
    day=np.array([str(r["day"]) for r in races])
    program=np.array([int(r["raceNo"]) for r in races])
    if np.any((program<1)|(program>12)):raise RuntimeError("INVALID_PROGRAM")
    band=np.asarray(fields,dtype=int)
    # fieldSize is a pre-race categorical bin, not the raw horse count.
    if np.any((band<0)|(band>20)):raise RuntimeError('INVALID_FIELD_BIN')
    if np.any((market_state<0)|(market_state>30)):raise RuntimeError('INVALID_MARKET_STATE')
    if np.any((odds_gap_state<0)|(odds_gap_state>10)):raise RuntimeError("INVALID_ODDS_GAP_STATE")
    # Pre-race metadata only. Missing values remain UNKNOWN.
    def pre_race_course(r):
        surface=str(r.get("surface",r.get("trackType","UNKNOWN"))).strip().lower()
        distance=r.get("distance",r.get("distanceM"))
        try: distance_band=int(distance)//400 if distance is not None else -1
        except (ValueError,TypeError): distance_band=-1
        going=str(r.get("going",r.get("trackCondition","UNKNOWN"))).strip().lower()
        return (surface,distance_band,going)
    course=[pre_race_course(r) for r in races]
    # Hierarchical, pre-race regime routing: avoid nearly unique nine-way keys.
    # The coarse key ensures training support; specific conditions are activated
    # only when sufficient historical observations exist before the test quarter.
    base_keys=[(venue[i],int(quarter[i]),int(band[i]),int(market_state[i])) for i in range(n)]
    # Program position is known before the race; include it only at the detailed tier.
    program_bands=np.minimum((program-1)//4,2)
    detailed_keys=[base_keys[i]+(int(program_bands[i]),int(odds_gap_state[i]),course[i][0],course[i][1],course[i][2]) for i in range(n)]
    keys=base_keys
    all_bets=[];coverage={};missing=0
    periods=[(y,q) for y in range(2023,2027) for q in range(1,5)]
    for target,q in periods:
        period=target*4+q
        train=np.flatnonzero((year*4+quarter<period)&(year*4+quarter>=period-24)&(year>=2017))
        test=np.flatnonzero((year==target)&(quarter==q))
        if not len(test):continue
        if not len(train):raise RuntimeError("NO_PAST_TRAINING")
        # Directly discover high-hit and largest-race-excluded cash candidates from past settlements.
        v=money[train]
        candidates=[]
        for lo,hi in MARKETS:
            hits=np.count_nonzero(v[:,lo:hi],axis=0)
            robust=v[:,lo:hi].sum(axis=0)-v[:,lo:hi].max(axis=0)
            a=np.argsort(-hits,kind="stable")[:3]+lo
            b=np.argsort(-robust,kind="stable")[:4]+lo
            # Joint cash complement: identify tickets that add robust cash to
            # another market's high-hit anchor, not merely strong solo tickets.
            # All inputs are from completed pre-target-quarter races.
            complements=[]
            for other_lo,other_hi in MARKETS:
                if other_lo==lo:continue
                other_cash=v[:,other_lo:other_hi]
                other_hits=np.count_nonzero(other_cash,axis=0)
                other_robust=other_cash.sum(axis=0)-other_cash.max(axis=0)
                # Two economically distinct anchors: frequent small payouts and
                # large but largest-race-excluded cash. Evaluate their joint
                # race-level cash, rather than filtering each leg independently.
                anchors={int(other_lo+np.argmax(other_hits)),
                         int(other_lo+np.argmax(other_robust))}
                for anchor in sorted(anchors):
                    combined=v[:,lo:hi]+v[:,anchor,None]
                    joint_robust=combined.sum(axis=0)-combined.max(axis=0)
                    complements.append(np.argsort(-joint_robust,kind="stable")[:2]+lo)
            # New regime-aware cash discovery: quarter-specific payout leaders
            # are admitted before joint pairing, even when absent from global
            # leaders. The test quarter's payouts never enter this discovery.
            seasonal=[]
            for past_q in (1,2,3,4):
                qi=train[quarter[train]==past_q]
                if len(qi)<60:continue
                seasonal_cash=money[qi,lo:hi]
                seasonal_robust=seasonal_cash.sum(axis=0)-seasonal_cash.max(axis=0)
                seasonal.append(int(lo+np.argmax(seasonal_robust)))
                seasonal_hits=np.count_nonzero(seasonal_cash,axis=0)
                seasonal.append(int(lo+np.argmax(seasonal_hits)))
            candidates.append(list(dict.fromkeys(map(int,list(a)+list(b)+seasonal+[x for z in complements for x in z])))[:24])
        options=[]
        for market_a in range(6):
            for market_b in range(market_a+1,6):
                for a in candidates[market_a]:
                    for b in candidates[market_b]:
                        for sa,sb in ((100,100),(100,200),(200,100)):
                            options.append((a,b,sa,sb))
        # Prior-period regime-specific cash ledger with shrinkage for sparse states.
        groups=defaultdict(list)
        # A detailed state must have >=60 historical races; otherwise back off
        # to the venue/season/field/market regime, and finally venue-level.
        detailed_counts=defaultdict(int)
        base_counts=defaultdict(int)
        for i in train:
            detailed_counts[detailed_keys[int(i)]]+=1
            base_counts[base_keys[int(i)]]+=1
        def regime(i):
            i=int(i)
            if detailed_counts[detailed_keys[i]]>=60:
                return ("detail",)+detailed_keys[i]
            if base_counts[base_keys[i]]>=60:
                return ("base",)+base_keys[i]
            return ("venue",venue[i])
        keys=[regime(i) for i in range(n)]
        for i in train:groups[keys[int(i)]].append(int(i))
        def score_option(ix,option):
            a,b,sa,sb=option
            p=(money[ix,a]*sa+money[ix,b]*sb)//100
            stake=(sa+sb)*len(ix)
            if not stake:return -1e9
            years=year[ix]
            # Cash return after removing largest race, and worst annual cash ROI.
            robust=(int(p.sum())-int(p.max()))/stake
            annual=[(int(p[years==yy].sum())-int(p[years==yy].max()))/((sa+sb)*int(np.sum(years==yy))) for yy in np.unique(years)]
            # Temporal cash stability: discourage a single lucrative quarter from
            # dominating the policy chosen for the next, unseen quarter.
            quarters_seen=year[ix]*4+quarter[ix]
            quarterly=[]
            for period_seen in np.unique(quarters_seen):
                qpaid=p[quarters_seen==period_seen]
                if len(qpaid)>=5:
                    quarterly.append((int(qpaid.sum())-int(qpaid.max()))/((sa+sb)*len(qpaid)))
            # Trim sparse quarters; all figures use only past settled cash.
            qfloor=float(np.percentile(quarterly,25)) if quarterly else min(annual)
            return robust+0.1*min(annual)+0.15*qfloor
        # Screen the full joint-pair universe using exact vectorized cash settlements.
        # The expensive year/quarter stability objective is then evaluated on a
        # diversified shortlist, not on tens of thousands of Python loops per regime.
        # No test-period cash is accessed. This is candidate screening, not a model.
        option_array=np.asarray(options,dtype=np.int64)
        def rank_options(source,limit):
            source=np.asarray(source,dtype=np.int64)
            if not len(source):return []
            robust_scores=np.empty(len(options),dtype=np.float64)
            annual_floor=np.empty(len(options),dtype=np.float64)
            source_year=year[source]
            year_masks=[source_year==yy for yy in np.unique(source_year)]
            for start in range(0,len(options),128):
                stop=min(start+128,len(options))
                batch=option_array[start:stop]
                a,b,sa,sb=(batch[:,k] for k in range(4))
                paid=(money[source[:,None],a[None,:]]*sa[None,:]+
                      money[source[:,None],b[None,:]]*sb[None,:])//100
                stakes=(sa+sb).astype(np.float64)
                robust_scores[start:stop]=(paid.sum(axis=0)-paid.max(axis=0))/(len(source)*stakes)
                floors=[]
                for mask in year_masks:
                    annual_paid=paid[mask]
                    floors.append((annual_paid.sum(axis=0)-annual_paid.max(axis=0))/(mask.sum()*stakes))
                annual_floor[start:stop]=np.min(np.stack(floors),axis=0)
            # Preserve both high-robust and year-balanced complementary tickets.
            # Stable tie ordering makes runs reproducible.
            width=max(128,limit*16)
            ids=set(np.argsort(-robust_scores,kind='stable')[:width].tolist())
            ids.update(np.argsort(-annual_floor,kind='stable')[:width].tolist())
            ids.update(np.argsort(-(robust_scores+0.1*annual_floor),kind='stable')[:width].tolist())
            return sorted((options[k] for k in ids),key=lambda x:score_option(source,x),reverse=True)[:limit]
        # Global pool is a fallback only, never an independently adopted model.
        global_rank=rank_options(train,16)
        policies={}
        for key,ix in groups.items():
            ix=np.asarray(ix,dtype=int)
            source=ix if len(ix)>=60 else train[venue[train]==key[1]]
            if len(source)<60:source=train
            policies[key]=rank_options(source,8)
        # Jointly optimize assignments on a complete historical 5R-per-venue-day slate.
        train_days=defaultdict(list)
        for i in train:train_days[(day[i],venue[i])].append(int(i))
        current={key:opts[0] for key,opts in policies.items()}
        fallback=global_rank[0]
        def priority(key,assignment):
            ix=groups.get(key,[])
            if not ix:return -1
            return score_option(np.asarray(ix,dtype=int),assignment)
        # Learn venue-season program-band marginal cash priority exclusively
        # from completed training races; never rank test races by their payout.
        band_history=defaultdict(list)
        for i in train:
            band_history[(venue[i],int(quarter[i]),int(program_bands[i]))].append(int(i))
        def race_priority(i,assign):
            i=int(i)
            option=assign.get(keys[i],fallback)
            a,b,sa,sb=option
            hist=band_history.get((venue[i],int(quarter[i]),int(program_bands[i])),[])
            if len(hist)<20:
                hist=train[(venue[train]==venue[i])&(program_bands[train]==program_bands[i])]
            if len(hist)<20:return priority(keys[i],option)
            h=np.asarray(hist,dtype=int)
            paid=(money[h,a]*sa+money[h,b]*sb)//100
            robust=(int(paid.sum())-int(paid.max()))/((sa+sb)*len(h))
            base=priority(keys[i],option)
            return (len(h)*robust+40*base)/(len(h)+40)
        # Cache immutable, training-only priority by regime/option. During
        # coordinate descent only the changed regime needs a new priority.
        # This removes repeated historical payout reductions inside every sort.
        priority_cache={}
        def cached_priority(i,assign):
            i=int(i);key=keys[i];option=assign.get(key,fallback)
            ck=(key,option,int(program_bands[i]),int(quarter[i]))
            if ck not in priority_cache:
                priority_cache[ck]=race_priority(i,assign)
            return priority_cache[ck]
        train_day_lists=list(train_days.values())
        def slate(assign):
            return [i for indices in train_day_lists for i in
                    sorted(indices,key=lambda j:(-cached_priority(j,assign),int(program[j])))[:5]]
        chosen=slate(current)
        def objective(assign,indices):
            if not indices:return (-1e9,-1e9)
            ix=np.asarray(indices,dtype=int)
            # Group by assigned ticket, using vectorized cash lookup instead
            # of Python per-race dictionary construction on every trial.
            payouts=np.empty(len(ix),dtype=np.int64)
            stakes=np.empty(len(ix),dtype=np.int64)
            by_option=defaultdict(list)
            for pos,i in enumerate(ix):
                by_option[assign.get(keys[int(i)],fallback)].append(pos)
            for (a,b,sa,sb),positions in by_option.items():
                pos=np.asarray(positions,dtype=int)
                payouts[pos]=(money[ix[pos],a]*sa+money[ix[pos],b]*sb)//100
                stakes[pos]=sa+sb
            total_stake=int(stakes.sum())
            robust=(int(payouts.sum())-int(payouts.max()))/total_stake
            annual=[]
            for yy in np.unique(year[ix]):
                mask=year[ix]==yy
                p=payouts[mask]
                annual.append((int(p.sum())-int(p.max()))/int(stakes[mask].sum()))
            floor=min(annual)
            quarter_robust=[]
            periods_ix=year[ix]*4+quarter[ix]
            for pq in np.unique(periods_ix):
                mask=periods_ix==pq
                if int(mask.sum())>=5:
                    p=payouts[mask]
                    quarter_robust.append((int(p.sum())-int(p.max()))/int(stakes[mask].sum()))
            qfloor=float(np.percentile(quarter_robust,25)) if quarter_robust else floor
            return (robust+0.1*floor+0.15*qfloor,robust)
        for _ in range(3):
            previous_assignments=current.copy()
            for key in sorted(current):
                best=current[key];bestscore=objective(current,slate(current))
                # Re-select the complete historical 5R slate for every trial.
                # Scoring a changed rule against a stale slate biases the search:
                # it ignores the races displaced by the candidate rule.
                for option in policies[key]:
                    current[key]=option
                    trial_slate=slate(current)
                    val=objective(current,trial_slate)
                    if val>bestscore:bestscore=val;best=option
                current[key]=best
                chosen=slate(current)
            new=slate(current)
            # Convergence requires stable assignments AND a stable slate. The
            # prior comparison always succeeded because chosen was refreshed
            # inside the key loop, silently preventing further passes.
            if new==chosen and current==previous_assignments:break
            chosen=new
        test_days=defaultdict(list)
        for i in test:test_days[(day[i],venue[i])].append(int(i))
        counts=defaultdict(int)
        for _,indices in test_days.items():
            selected=sorted(indices,key=lambda j:(-cached_priority(j,current),int(program[j])))[:5]
            counts[len(selected)]+=1
            for i in selected:
                a,b,sa,sb=current.get(keys[i],fallback)
                all_bets.append(dict(raceId=str(races[i]["id"]),day=day[i],venue=venue[i],year=target,quarter=q,
                    marketA=next(k for k,(lo,hi) in enumerate(MARKETS) if lo<=a<hi),
                    marketB=next(k for k,(lo,hi) in enumerate(MARKETS) if lo<=b<hi),
                    ticketA=a,ticketB=b,stakeA=sa,stakeB=sb,stakeYen=sa+sb,
                    paidYen=int((money[i,a]*sa+money[i,b]*sb)//100)))
        coverage[f"{target}Q{q}"]=dict(trainRaces=len(train),testRaces=len(test),
            detailedRegimeTestRaces=sum(keys[int(i)][0]=="detail" for i in test),
            baseRegimeTestRaces=sum(keys[int(i)][0]=="base" for i in test),
            venueFallbackTestRaces=sum(keys[int(i)][0]=="venue" for i in test),
            venueDays=len(test_days),selected5=counts[5],selected3to5=sum(v for k,v in counts.items() if 3<=k<=5),
            below3=sum(v for k,v in counts.items() if k<3))
    return all_bets,coverage,dict(surfaceKnown=sum(c[0] not in ("unknown","") for c in course),distanceKnown=sum(c[1]>=0 for c in course),goingKnown=sum(c[2] not in ("unknown","") for c in course),total=len(course))
def main():
    if "--self-test" in sys.argv:
        assert summarize([dict(stakeYen=200,paidYen=500),dict(stakeYen=200,paidYen=100)])["minusMaxRaceRoiPct"]==25
        assert len(MARKETS)==6 and sum(hi-lo for lo,hi in MARKETS)==336
        assert list(np.minimum((np.array([1,4,5,8,9,12])-1)//4,2))==[0,0,1,1,2,2]
        assert list(np.minimum(np.array([0,1,2,7])//2,3))==[0,0,1,3]
        print("QUARTERLY_JOINT_CASH_SELF_TEST_OK");return
    src=ROOT/"scripts/research-nov2026-seasonal-ensemble-cash-first.py"
    spec=importlib.util.spec_from_file_location("cashsrc",src)
    mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
    races,cash,cat,widths,types,rid,year,quarter,joint=mod.obtain_rows()
    if len(cash)!=336*len(races) or np.any(cash<0):raise RuntimeError("INVALID_CASH")
    fields=cat['fieldSize'].reshape(len(races),336)[:,0].astype(int)
    # Favourite-odds category is observable before the race; do not use payout to route.
    fav=cat['favOdds'].reshape(len(races),336)[:,0].astype(int)
    market_state=np.minimum(fav//2,3)
    # Pre-race odds-category spread is observable from the existing seven-horse tickets.
    # It avoids requesting a non-existent favGap column; not official T-15 odds.
    odds_bins=cat["oddsGeom"].reshape(len(races),336)[:,:7].astype(int)
    # Observed pre-race odds-category dispersion across seven single-horse tickets.
    # This is a categorical spread, NOT a favourite/runner-up odds ratio.
    odds_gap=np.minimum(np.maximum(np.max(odds_bins,axis=1)-np.min(odds_bins,axis=1),0),3)
    bets,coverage,course_coverage=run(races,cash,year,quarter,fields,market_state,odds_gap)
    if any(b["marketA"]==b["marketB"] for b in bets):raise RuntimeError("DUPLICATE_MARKET")
    if len({b["raceId"] for b in bets})!=len(bets):raise RuntimeError("DUPLICATE_RACE")
    report=dict(researchOnly=True,adoptable=False,officialT15Verified=False,officialJraPayoutReconciled=False,
        source="third_party_unreconciled",priorExposure2025And2026=True,
        regimeDimensions=["venue","quarter","fieldSizeCategory","programNumberBand","preRaceFavouriteOddsBand","preRaceTopSevenOddsCategorySpread","preRaceSurfaceIfAvailable","preRaceDistance400mBandIfAvailable","preRaceGoingIfAvailable"],courseMetadataCoverage=course_coverage,marketCompetitionCoverage=dict(total=len(odds_gap),known=int(np.sum((odds_gap>=0)&(odds_gap<4))),bins={str(k):int(np.sum(odds_gap==k)) for k in range(4)}),
        missingOfficialVenueDays="NOT_VERIFIED",candidateRaces=len(races),
        combined=summarize(bets),years={str(y):summarize([b for b in bets if b["year"]==y]) for y in range(2023,2027)},
        quarters={f"{y}Q{q}":summarize([b for b in bets if b["year"]==y and b["quarter"]==q]) for y in range(2023,2027) for q in range(1,5)},
        coverage=coverage)
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    with gzip.open(BETS,"wt",encoding="utf8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(bets[0]) if bets else ["raceId"]);w.writeheader();w.writerows(bets)
    print("QUARTERLY_JOINT_CASH_RESULT",json.dumps(report,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
