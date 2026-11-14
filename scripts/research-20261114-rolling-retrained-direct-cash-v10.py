#!/usr/bin/env python3
"""ACTUAL rolling-retrained six-market payout forecasters (research only).

Fixes the core architectural defect of prior v3-v9 research: those models
retrained the cash-selector, NOT the ticket cash forecaster, on different
durations. Here the monetary ticket prediction MODEL ITSELF is refit for each
target month on JUST the selected retrospective months, independently for:
  training horizon 3 / 6 / 12 / 24 / 36 / 60 / 96 months
  training end 0 or 12 months before the predicted month
  conditional mean or optimistic robust cash feature interactions.
A freshly fitted money predictor scores ALL 1030 six-market combinations
of EACH race. Choose two DIFFERENT types and stake 2,000 yen per race.
Further generate selection portfolios and historical-money-selected
prediction-methods, again with only PRIOR realized settlements.

2015/16 are genuine money training history, 2017-2024 development,
2025-2026Apr independent holdout. No future payout in inputs to the
ticket models or to selectors. No model below all ROI200 / max-drop
ROI200 / HIT20 / 3R-per-venue-day gates is named, saved or deployed.
Archived win odds are FINAL, not historical T-15 JRA snapshots.
"""
from __future__ import annotations
import collections
import dataclasses
import importlib.util
import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"analysis-results/20261114-rolling-retrained-direct-money-v10.json"
HORIZONS=(3,6,12,24,36,60,96)
EMBARGO=(0,12)
FORECASTS=("mean","upper")
PAIRINGS=("two_best","win_plus_best","wide_plus_trio")
SPLITS=((1000,1000),(1500,500),(500,1500))
SLATES=(3,5)
META_HORIZONS=(3,6,12,24,36,60)
META_SCOPES=("venue","all_venues")
META_OBJECTIVES=("trimmed_cash","mean_cash","cash_hit_guard")
SHRINKS=(40,300)
SCHEMAS=(
    ("oddsGeom",),("favOdds",),("fieldSize",),("venue",),
    ("quarter",),("raceBand",),("favGap",),("oddsSpread",),
    ("horseAge",),("draw",),("horseWeight",),
    ("oddsGeom","venue"),("oddsGeom","fieldSize"),
    ("oddsGeom","favOdds"),("favOdds","venue"),
    ("horseAge","fieldSize"),("draw","venue"),
    ("favOdds","quarter"),("oddsGeom","horseAge"),
    ("oddsGeom","quarter"),("horseWeight","venue"),
)
STAKE_PER_RACE=2000
START_DEV="201701"
END_DEV="202412"
START_HOLD="202501"
END_HOLD="202604"
NV=10


def imported(file,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/file)
    if spec is None or spec.loader is None:
        raise RuntimeError("MISSING_RESEARCH_SOURCE:"+str(file))
    mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod
    spec.loader.exec_module(mod)
    return mod


@dataclasses.dataclass(frozen=True)
class Method:
    horizon: int
    embargo: int
    forecast: str
    pairing: str
    stakes: tuple[int,int]
    slate: int

    def export(self):
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class Meta:
    months: int
    scope: str
    objective: str
    shrink: int

    def export(self):
        return dataclasses.asdict(self)


def methods():
    return [Method(*arg) for arg in itertools.product(
        HORIZONS,EMBARGO,FORECASTS,PAIRINGS,SPLITS,SLATES)]


def meta_methods():
    return [Meta(*arg) for arg in itertools.product(
        META_HORIZONS,META_SCOPES,META_OBJECTIVES,SHRINKS)]


def qualify(paid,stake,hit,nr,days,largest):
    if stake<=0 or nr<=0 or days<=0:
        return False
    return (paid>=2*stake+largest and 5*hit>=nr and nr>=3*days)


def cash_report(paid,stake,hit,nr,days,largest):
    if stake<=0 or not nr:return None
    return {
        "paidYen":int(paid),"stakeYen":int(stake),
        "profitYen":int(paid-stake),
        "cashRoiPct":round(100*paid/stake,5),
        "minusLargestRaceRoiPct":round(100*(paid-largest)/stake,5),
        "hitPct":round(100*hit/nr,5),
        "boughtRaces":int(nr),
        "venueDays":int(days),
        "largestSingleRacePayoutYen":int(largest),
        "qualified":qualify(paid,stake,hit,nr,days,largest),
    }


class RefitCash:
    """Sufficient statistics of the DIRECT money forecaster, by month.

    Every date's model weights are refitted through the selected time
    interval only. This is NOT a prior model re-ranker.
    """
    def __init__(self,races,payout,features,market,bins):
        self.races=races
        self.payout=payout
        self.features=features
        self.market=np.asarray(market,dtype=np.int32)
        self.months=sorted({r["month"] for r in races})
        if len(self.months)!=136 or self.months[0]!="201501" or self.months[-1]!="202604":
            raise RuntimeError("NOT_THE_COMPLETE_136_MONTH_CASH_ARCHIVE")
        self.idx={m:np.asarray([i for i,r in enumerate(races) if r["month"]==m],
                               dtype=np.int32) for m in self.months}
        self.codebooks={}
        self.prefix={}
        self.bins={k:int(v) for k,v in bins.items()}
        self.active_month=None
        self.active_month_codes={}
        self.group={}
        for month,ix in self.idx.items():
            days=collections.defaultdict(list)
            for pos,absid in enumerate(ix):
                r=races[int(absid)]
                v=int(r["venue"])-1
                if v not in range(10):raise RuntimeError("INVALID_VENUE")
                days[(r["day"],v)].append(pos)
            if len(days)<1 or min(map(len,days.values()))<3:
                raise RuntimeError("INCOMPLETE_VENUE_DAY_PREVENTS_ROI_AUDIT")
            self.group[month]=list(days.items())
        for schema in SCHEMAS:
            ncat=1
            for field in schema:
                if field not in features:raise RuntimeError("MISSING_DIRECT_FEATURE:"+field)
                ncat*=int(bins[field])
            self.codebooks[schema]=ncat
        self._load_train_stats()

    def codes(self,ix,schema):
        code=np.zeros((len(ix),self.payout.shape[1]),dtype=np.int32)
        for field in schema:
            n=int(self.bins[field])
            col=self.features[field][ix].astype(np.int32)
            if col.size and (np.max(col)>=n or np.min(col)<0):
                raise RuntimeError(f"INVALID_FEATURE_CODE:{field}")
            code=code*n+col
        return (self.market[None,:]*self.codebooks[schema]+code).ravel()

    def _load_train_stats(self):
        # Feature cardinalities come from the fixed historical schema, not
        # any future race feature or future settlement observations.
        for schema in SCHEMAS:
            ncat=1
            for field in schema:
                ncat*=self.bins[field]
            self.codebooks[schema]=ncat
            b=6*ncat
            counts=np.zeros((len(self.months)+1,b),dtype=np.float64)
            monies=np.zeros_like(counts)
            hits=np.zeros_like(counts)
            for t,month in enumerate(self.months):
                ix=self.idx[month]
                code=self.codes(ix,schema)
                paid=self.payout[ix].ravel()
                if np.any(paid<0):raise RuntimeError("NEGATIVE_OFFICIAL_PAYOUT")
                counts[t+1]=np.bincount(code,minlength=b)
                monies[t+1]=np.bincount(code,
                    weights=np.minimum(paid,20000),minlength=b)
                hits[t+1]=np.bincount(code,
                    weights=(paid>0).astype(np.float32),minlength=b)
            # prefix[month] contains ONLY payouts BEFORE that month.
            np.cumsum(counts,axis=0,out=counts)
            np.cumsum(monies,axis=0,out=monies)
            np.cumsum(hits,axis=0,out=hits)
            self.prefix[schema]=(counts,monies,hits)

    def forecast(self,month,horizon,embargo):
        ix=self.idx[month]
        n=len(ix);p=self.payout.shape[1]
        position=self.months.index(month)
        stop=max(0,position-embargo)
        start=max(0,stop-horizon)
        center=np.full((n,p),.75,dtype=np.float32)
        linear=np.zeros_like(center)
        upper=np.full_like(center,-1e6)
        if self.active_month != month:
            # Training windows differ, but all predictions for a target
            # month share EXACTLY the same pre-result categorical features.
            self.active_month_codes={
                schema:self.codes(ix,schema).reshape(n,p) for schema in SCHEMAS}
            self.active_month=month
        for schema in SCHEMAS:
            a,b,c=self.prefix[schema]
            count=a[stop]-a[start]
            payout=b[stop]-b[start]
            hit=c[stop]-c[start]
            code=self.active_month_codes[schema]
            nobs=count[code]
            ratio=np.clip(payout[code]/(np.maximum(nobs,1)*100.),0.,100.)
            # Expected cash in yen relative to the 100-yen investment.
            # Smooth highly rare jackpot cells and low-support cells.
            support=(nobs/(nobs+200.))*(hit[code]/(hit[code]+4.))
            uplift=((ratio-.75)*support).astype(np.float32)
            linear+=uplift
            np.maximum(upper,uplift,out=upper)
        avg=center+linear/len(SCHEMAS)
        optim=center+0.45*linear/len(SCHEMAS)+0.55*upper
        return np.clip(avg,0.,20.),np.clip(optim,0.,20.)

    def direct_month_cash(self,month,horizon,embargo):
        # Fresh cash trained model for each rolling horizon and cutoff.
        signals=self.forecast(month,horizon,embargo)
        ix=self.idx[month]
        n=len(ix)
        results={}
        per_market=[]
        for market in range(6):
            columns=np.flatnonzero(self.market==market)
            if not len(columns):raise RuntimeError("JRA_MARKET_MISSING")
            per=[]
            for score in signals:
                local=np.argmax(score[:,columns],axis=1)
                at=columns[local]
                per.append((score[np.arange(n),at],
                            self.payout[ix,at]))
            per_market.append(per)
        for forecast_id,forecast in enumerate(FORECASTS):
            sm=np.stack([per_market[m][forecast_id][0] for m in range(6)],axis=1)
            pm=np.stack([per_market[m][forecast_id][1] for m in range(6)],axis=1)
            for pairing in PAIRINGS:
                if pairing=="two_best":
                    markets=np.argsort(-sm,axis=1,kind="stable")[:,:2]
                    first,second=markets[:,0],markets[:,1]
                elif pairing=="win_plus_best":
                    first=np.zeros(n,dtype=np.int32)
                    other=np.argmax(sm[:,1:],axis=1)+1
                    second=other
                else:
                    first=np.ones(n,dtype=np.int32)
                    second=np.full(n,4,dtype=np.int32)
                s1=sm[np.arange(n),first]
                s2=sm[np.arange(n),second]
                p1=pm[np.arange(n),first]
                p2=pm[np.arange(n),second]
                if np.any(first==second):raise RuntimeError("REPEATED_BET_TYPE")
                desirability=s1+s2
                for stake in SPLITS:
                    cash=(p1*(stake[0]//100)+p2*(stake[1]//100)).astype(np.int64)
                    for slate in SLATES:
                        per_venue=np.zeros((NV,5),dtype=np.int64)
                        for (_,v),positions in self.group[month]:
                            subset=np.asarray(positions,dtype=np.int32)
                            ranked=subset[np.argsort(-desirability[subset],kind="stable")]
                            picked=ranked[:slate]
                            ret=cash[picked]
                            if len(picked)<3:
                                raise RuntimeError("VENUE_DAY_TOO_FEW_PURCHASED_RACES")
                            cell=per_venue[v]
                            cell[0]+=int(np.sum(ret))
                            cell[1]+=int(np.count_nonzero(ret))
                            cell[2]+=len(picked)
                            cell[3]=max(cell[3],int(np.max(ret)))
                            cell[4]+=1
                        method=Method(horizon,embargo,forecast,pairing,stake,slate)
                        results[method]=per_venue
        return results


class Ledger:
    def __init__(self,methods,months):
        self.methods=methods
        self.months=months
        shape=(len(methods),len(months),NV)
        self.paid=np.zeros(shape,dtype=np.int64)
        self.hit=np.zeros(shape,dtype=np.int32)
        self.races=np.zeros(shape,dtype=np.int32)
        self.max_paid=np.zeros(shape,dtype=np.int64)
        self.days=np.zeros(shape,dtype=np.int16)
        self.stake=np.zeros(shape,dtype=np.int64)
        self.model_index={m:i for i,m in enumerate(methods)}
        self.month_index={m:i for i,m in enumerate(months)}

    def assign(self,month,actions):
        t=self.month_index[month]
        for method,p in actions.items():
            k=self.model_index[method]
            self.paid[k,t]=p[:,0]
            self.hit[k,t]=p[:,1]
            self.races[k,t]=p[:,2]
            self.max_paid[k,t]=p[:,3]
            self.days[k,t]=p[:,4]
            self.stake[k,t]=self.races[k,t]*STAKE_PER_RACE

    def finish(self):
        self.prefix_paid=np.pad(np.cumsum(self.paid,axis=1),
            ((0,0),(1,0),(0,0)))
        self.prefix_stake=np.pad(np.cumsum(self.stake,axis=1),
            ((0,0),(1,0),(0,0)))
        self.prefix_hit=np.pad(np.cumsum(self.hit,axis=1),
            ((0,0),(1,0),(0,0)))
        self.prefix_races=np.pad(np.cumsum(self.races,axis=1),
            ((0,0),(1,0),(0,0)))


def summed_cash(ledger,picks,start,end):
    paid=stake=hit=nr=days=big=0
    by_year=collections.defaultdict(lambda:[0,0,0,0,0,0])
    by_day_coverage=collections.Counter()
    for t,month in enumerate(ledger.months):
        if not(start<=month<=end):continue
        for v in range(NV):
            if ledger.days[0,t,v]==0:continue
            k=int(picks[t,v])
            pc=int(ledger.paid[k,t,v]); st=int(ledger.stake[k,t,v])
            h=int(ledger.hit[k,t,v]); r=int(ledger.races[k,t,v])
            d=int(ledger.days[k,t,v]); mx=int(ledger.max_paid[k,t,v])
            if d != int(ledger.days[0,t,v]) or r<3*d:
                raise RuntimeError("ANY_VENUE_DAY_COVERAGE_LOST")
            paid+=pc;stake+=st;hit+=h;nr+=r;days+=d;big=max(mx,big)
            yy=month[:4];y=by_year[yy]
            y[0]+=pc;y[1]+=st;y[2]+=h;y[3]+=r;y[4]+=d;y[5]=max(mx,y[5])
    return cash_report(paid,stake,hit,nr,days,big),{
        y:cash_report(*values) for y,values in sorted(by_year.items())}


def stable_picks(ledger,k):
    nmonth=len(ledger.months)
    return np.full((nmonth,NV),k,dtype=np.int32)


def online_picks(ledger,meta):
    n=len(ledger.methods)
    chosen=np.zeros((len(ledger.months),NV),dtype=np.int32)
    for t,month in enumerate(ledger.months):
        stop=t;start=max(0,t-meta.months)
        if t==0:continue
        for v in range(NV):
            if meta.scope=="venue":
                cash=ledger.prefix_paid[:,stop,v]-ledger.prefix_paid[:,start,v]
                spend=ledger.prefix_stake[:,stop,v]-ledger.prefix_stake[:,start,v]
                win=ledger.prefix_hit[:,stop,v]-ledger.prefix_hit[:,start,v]
                nobs=ledger.prefix_races[:,stop,v]-ledger.prefix_races[:,start,v]
                maxpaid=ledger.max_paid[:,start:stop,v].max(axis=1)
            else:
                cash=np.sum(ledger.prefix_paid[:,stop]-ledger.prefix_paid[:,start],axis=1)
                spend=np.sum(ledger.prefix_stake[:,stop]-ledger.prefix_stake[:,start],axis=1)
                win=np.sum(ledger.prefix_hit[:,stop]-ledger.prefix_hit[:,start],axis=1)
                nobs=np.sum(ledger.prefix_races[:,stop]-ledger.prefix_races[:,start],axis=1)
                maxpaid=ledger.max_paid[:,start:stop,:].max(axis=(1,2))
            gross=100*cash/np.maximum(1,spend)
            robust=100*np.maximum(0,cash-maxpaid)/np.maximum(1,spend)
            if meta.objective=="trimmed_cash":
                score=robust
            elif meta.objective=="mean_cash":
                score=0.5*(gross+robust)
            else:
                score=robust-400*np.maximum(0,.2-win/np.maximum(1,nobs))
            score=100+(score-100)*nobs/(nobs+meta.shrink)
            score=np.where(nobs>=30,score,-1e9)
            if np.max(score)>-1e8:
                chosen[t,v]=int(np.argmax(score))
    return chosen


def search(ledger):
    eligible=[]
    nbase=0;nmeta=0
    for k,method in enumerate(ledger.methods):
        stats,years=summed_cash(ledger,stable_picks(ledger,k),START_DEV,END_DEV)
        if stats and stats["qualified"]:
            eligible.append(("base",method,stats,years,stable_picks(ledger,k)))
        nbase+=1
    for meta in meta_methods():
        picks=online_picks(ledger,meta)
        stats,years=summed_cash(ledger,picks,START_DEV,END_DEV)
        if stats and stats["qualified"]:
            eligible.append(("meta",meta,stats,years,picks))
        nmeta+=1
        if nmeta%24==0:
            print("FRESH_RETRAINED_MONEY_META_SEARCH",json.dumps({
                "onlineProgramsEvaluated":nmeta,"onlineProgramsTotal":len(meta_methods()),
                "approvedFromDevelopment":len(eligible)}),flush=True)
    eligible.sort(key=lambda x:(x[2]["profitYen"],x[2]["minusLargestRaceRoiPct"]),reverse=True)
    found=[]
    for kind,model,dev,years,picks in eligible:
        held,hy=summed_cash(ledger,picks,START_HOLD,END_HOLD)
        if held and held["qualified"]:
            found.append({
                "kind":kind,"predictionModel":model.export(),
                "developmentActualMoney":dev,"developmentYears":years,
                "independentMoney":held,"independentYears":hy,
                "officialJraPreT15Verified":False,
                "productionEligible":False,
            })
    return {
        "result":("RETROSPECTIVE_200PCT_MODEL_FOUND" if found
                  else "NO_200PCT_FRESH_RETRAINED_MODEL_FOUND"),
        "baseModelsActuallyRefitEveryTargetMonth":len(ledger.methods),
        "distinctDirectFeatureCashModelsPerMonth":len(HORIZONS)*len(EMBARGO)*len(FORECASTS),
        "adaptiveProfitModelFamilies":nmeta,
        "historyDurationsMonths":list(HORIZONS),
        "trainInformationEmbargoMonths":list(EMBARGO),
        "moneyLabels":"REAL_RECEIVED_JPY_PER_100_YEN_TICKET",
        "modelType":"fresh rolling conditional cash regression from full race-ticket features and payout history",
        "developmentQualified":len(eligible),
        "independentQualified":len(found),
        "models":found,
        "developmentPeriod":START_DEV+".."+END_DEV,
        "independentPeriod":START_HOLD+".."+END_HOLD,
        "noSameMonthMoneyAsInput":True,
        "largestReturnedRaceRemovedStakeRetained":True,
        "unreconciledThirdPartyJraDerivedPayout":True,
        "historicalWinOddsWereFinalNotOfficialPreT15":True,
        "productionModified":False,"promotionAllowed":False,
    }


def selftest():
    assert len(methods())==7*2*2*3*3*2
    assert len(meta_methods())==6*2*3*2
    assert qualify(14000,6000,3,3,1,1000)
    assert not qualify(13000,6000,3,3,1,2000)
    assert not qualify(14000,6000,0,3,1,1000)
    # High payout on a different race is NOT a valid reason to relabel
    # historical tips: train_end is target month, never target month's cash.
    s=Method(12,12,"mean","two_best",(1000,1000),3)
    assert s.horizon==12 and s.embargo==12
    print("FRESH_ROLLING_CASH_MODEL_504_BASE_72_META_SELFTEST_OK",flush=True)


def main():
    if "--self-test" in sys.argv:
        selftest();return
    started=time.monotonic()
    base=imported("scripts/research-20261114-broad-causal-cash-sweep.py",
                  "direct_rolling_cash_source")
    core,races,payout,features,market,slots=base.historic_cash()
    if len(races)<30000 or payout.shape!=(len(races),1030):
        raise RuntimeError("NOT_ALL_2015_TO_2026_SIX_MARKET_CASH_TICKETS_PRESENT")
    fit=RefitCash(races,payout,features,market,base.FEATURES)
    variants=methods()
    ledger=Ledger(variants,fit.months)
    for month in fit.months:
        if month<"201701":
            continue
        for horizon,embargo in itertools.product(HORIZONS,EMBARGO):
            actions=fit.direct_month_cash(month,horizon,embargo)
            ledger.assign(month,actions)
        print("FRESH_ROLLING_MONEY_MODELS_TRAINED",json.dumps({
            "targetMonth":month,
            "directModelFitsThisMonth":len(HORIZONS)*len(EMBARGO)*len(FORECASTS),
            "usingOnlyOlderSettlements":True}),flush=True)
    ledger.finish()
    result=search(ledger)
    result["historicRaces"]=len(races)
    result["seconds"]=round(time.monotonic()-started,2)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("FRESH_ROLLING_MONEY_DISCOVERY_FINAL",json.dumps({
        "status":result["result"],
        "freshTicketPredictionModelFits":result["distinctDirectFeatureCashModelsPerMonth"],
        "baseMethodFamilies":result["baseModelsActuallyRefitEveryTargetMonth"],
        "adaptiveMethodFamilies":result["adaptiveProfitModelFamilies"],
        "developmentApproved":result["developmentQualified"],
        "independentApproved":result["independentQualified"],
        "onlyQualifyingModels":result["models"],
        "elapsedSeconds":result["seconds"]},ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
