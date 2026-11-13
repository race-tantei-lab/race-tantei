#!/usr/bin/env python3
"""Frozen cash200 six-portfolio replay on OFFICIAL JRA FINAL WIN odds and D1 settlements.

READ ONLY. Research cutoff 2015-01..2026-04. Candidate identities
are frozen from the prior full-history mining; NO post-Aug result can select
a strategy or change the venue/quarter policy. All six market payouts are
reconciled against persisted rt_payouts for each completed race.

IMPORTANT: D1 rt_runners.win_odds has no proven identical timestamp to the
third-party historical final-odds archive. Forward ROI is therefore a
D1-stored-odds hypothetical replay, NOT an exact reproduction of final-odds
choices or proof of an actionable T-15 model. If eligible D1 coverage is
incomplete, report it and never describe results as all-races ROI.
"""
from __future__ import annotations
import collections, concurrent.futures, datetime as dt, importlib.util, json, math, re, sys, urllib.parse
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
SOURCE_RESULT=ROOT/"analysis-results/20261114-full-period-roi200-hit20-multiticket.json"
OUT=ROOT/"analysis-results/20261114-roi200-hit20-postaug-official-final-odds.json"
START="2026-08-01"
END="2026-11-14"
MONTHS=("2026-08","2026-09","2026-10","2026-11")
TYPES=("単勝","ワイド","馬連","馬単","3連複","3連単")
UNORDERED={"ワイド","馬連","3連複"}
VENUES={"札幌":1,"函館":2,"福島":3,"新潟":4,"東京":5,
        "中山":6,"中京":7,"京都":8,"阪神":9,"小倉":10}
def imp(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    if not spec or not spec.loader:raise RuntimeError("NO_IMPORT:"+str(path))
    m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m
    spec.loader.exec_module(m);return m
def norm_nums(text):
    return tuple(int(x) for x in re.findall(r"\d+",str(text)))
def venue_code(value):
    s=str(value or "").strip()
    if s in VENUES:return VENUES[s]
    if s.isdigit() and 1<=int(s)<=10:return int(s)
    raise RuntimeError("UNRECOGNIZED_JRA_VENUE:"+s)
def official_final_odds(bundle, historic, live):
    """JRA official *final* full-field win odds; no T-15 inference."""
    race=bundle["race"]
    url=str(race.get("resultUrl") or "")
    raw_url=urllib.parse.unquote(url)
    identity=re.search(r"(?:pw|sw)01sde(?:10|01)(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})",raw_url,re.I)
    if not identity:raise RuntimeError("OFFICIAL_JRA_RESULT_ID_MISSING")
    venue,year,meeting,meeting_day,race_no,ymd=identity.groups()
    day=str(race["raceDate"])
    if ymd!=day.replace("-","") or int(race_no)!=int(race["raceNo"]):
        raise RuntimeError("OFFICIAL_RESULT_RACE_IDENTITY_MISMATCH")
    if re.search(r"CNAME=sw01",url,re.I):
        parsed=urllib.parse.urlsplit(url)
        url=urllib.parse.urlunsplit(parsed._replace(netloc="sp.jra.jp"))
    jar=historic.http.cookiejar.CookieJar()
    opener=historic.urllib.request.build_opener(historic.urllib.request.HTTPCookieProcessor(jar))
    req=historic.urllib.request.Request(url,headers={
        "User-Agent":historic.USER_AGENT,"Accept-Language":"ja-JP,ja;q=0.9"})
    raw,_=historic.open_retry(opener,req,attempts=3,timeout=25)
    page=raw.decode("cp932","replace")
    core_id=venue+year+meeting+meeting_day+race_no+ymd
    names=sorted(set(re.findall(r"(?:pw|sw)151ou(?:10|S3)"
        +re.escape(core_id)+r"Z/[0-9A-Fa-f]{2}",page,re.I)))
    if len(names)!=1:raise RuntimeError("OFFICIAL_ODDS_LINK_NOT_UNIQUE:"+str(len(names)))
    cname=names[0]
    html,source=historic.post_odds(opener,cname,url)
    quote=(live.parse_mobile_win_odds(html) if cname.lower().startswith("sw")
           else historic.parse_win(live.BeautifulSoup(html,"html.parser")))
    active={int(x["horseNo"]) for x in bundle["runners"]
            if x.get("runnerStatus") in (None,"","active")}
    if len(set(quote).intersection(active))<max(10,len(active)-2):
       raise RuntimeError("JRA_FINAL_ODDS_FIELD_INCOMPLETE")
    return {int(k):float(v) for k,v in quote.items() if int(k) in active}
def d1_races():
    """Reconcile every 2026 Aug-Nov race with actual six-market settlement.

    Unlike the earlier 78-day run, missing D1 payout rows are supplied from
    an independent public finished-race archive after exact event checks.
    D1 status gaps use that same published final result. NO D1 WRITES.
    """
    live=imp("scripts/postaug-support-aug-nov-frozen-policy-recheck.py","postaug_query_helper")
    hist=imp("scripts/research-enrich-official-history-odds.py","jra_official_final_reader")
    pub=imp("scripts/research-20261114-public-results-six-payout-fallback.py","public_six_cash_supplement")
    live.START=START;live.END=END;live.MONTHS=MONTHS
    by_date,month_counts=live.d1_bundles()
    all_bundles=[bundle for day,bs in sorted(by_date.items()) for bundle in bs]
    if len(all_bundles)<900:raise RuntimeError("POSTAUG_D1_PROGRAM_TOO_SMALL")
    payments=collections.defaultdict(lambda:[{} for _ in TYPES])
    for month in MONTHS:
        nxt=(dt.date.fromisoformat(month+"-01")+dt.timedelta(days=35)).replace(day=1).isoformat()[:7]
        sql=("SELECT race_id raceId,bet_type betType,combination,payout_yen payoutYen "
             "FROM rt_payouts WHERE race_id>=? AND race_id<? "
             "AND bet_type IN ('単勝','ワイド','馬連','馬単','3連複','3連単') "
             "ORDER BY race_id,bet_type,combination")
        lines=live.paged(sql,[month+"-",nxt+"-"])
        for row in lines:
            typ=str(row["betType"]);m=TYPES.index(typ)
            combo=norm_nums(row["combination"])
            if typ in UNORDERED:combo=tuple(sorted(combo))
            expected=1 if typ=="単勝" else 3 if typ in ("3連複","3連単") else 2
            if len(combo)!=expected:raise RuntimeError("BAD_D1_PAYOUT_COMBINATION")
            yen=int(row["payoutYen"] or 0)
            if yen<=0 or yen%10:raise RuntimeError("INVALID_D1_SETTLED_PAYOUT")
            r=payments[str(row["raceId"])][m]
            if combo in r and r[combo]!=yen:raise RuntimeError("CONFLICTING_D1_PAYOUT")
            r[combo]=yen
        print("POSTAUG_D1_PAYOUTS_MONTH",json.dumps({"month":month,"rows":len(lines)}),flush=True)
    incomplete=[b for b in all_bundles if
        b["race"].get("status")!="finished" or
        any(not x for x in payments[str(b["race"]["raceId"])])]
    print("AUG_NOV_PAYOUT_SUPPLEMENT_START",json.dumps({
       "allRaceRowsInPastDateRange":len(all_bundles),
       "D1UnfinishedOrSixMarketMissing":len(incomplete),
       "allPayoutsAreRetrospectiveActualResults":True,
       "D1WriteOperations":0}),flush=True)
    fetched={};errors={};source_counts=collections.Counter()
    def retrieve(b):
        rid=str(b["race"]["raceId"])
        try:
            d,provenance=pub.fetch_public(b["race"])
            return rid,d,provenance,None
        except Exception as ex:return rid,None,None,str(ex)[:220]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for rid,d,provenance,error in pool.map(retrieve,incomplete):
            if error:errors[rid]=error
            else:
                fetched[rid]=d;source_counts["publicFinishedSixMarketPages"]+=1
    if errors:
        print("AUG_NOV_PAYOUT_SUPPLEMENT_ERRORS",json.dumps({
          "failed":len(errors),"examples":dict(list(errors.items())[:15])},ensure_ascii=False),flush=True)
    if fetched:
        for rid,d in fetched.items():
            # Strict overlap reconciliation, never override a conflicting
            # actual JRA row to make the retrospective ROI look better.
            payments[rid]=pub.integrate(payments[rid],d,rid)
    candidates=[];not_confirmed=[];short_field=[];count_finished=0
    expected=collections.Counter()
    for bundle in all_bundles:
        race=bundle["race"];rid=str(race["raceId"])
        if race.get("status")=="finished":
            count_finished+=1
        if race.get("status")!="finished" and rid not in fetched:
            not_confirmed.append(rid);continue
        if any(not x for x in payments[rid]):
            not_confirmed.append(rid);continue
        venue=venue_code(race.get("venue"))
        expected[(str(race["raceDate"]),venue)]+=1
        active=[x for x in bundle["runners"]
               if x.get("runnerStatus") in (None,"","active")]
        # The 2015..2026-Apr research dataset never selected a race with
        # fewer than ten horses; genuinely short fields are ineligible,
        # not a failure to download quote data.
        if len({int(h["horseNo"]) for h in active})<10:
            short_field.append(rid);continue
        candidates.append(bundle)
    print("POSTAUG_JRA_ALL_VENUE_DATES_AFTER_CASH_REPAIR",json.dumps({
      "allRows":len(all_bundles),"D1FinishedRows":count_finished,
      "completeRetrospectiveSixMarketCash":len(all_bundles)-len(not_confirmed),
      "publicSupplementedRacePayouts":len(fetched),
      "stillLackFinishedSettlements":len(not_confirmed),
      "genuineLessThan10RunnerRaces":len(short_field),
      "racesEligibleForOfficialOddsFetch":len(candidates),
      "completedVenueDays":len(expected)},ensure_ascii=False),flush=True)
    odds={};failures=collections.Counter();failed_rids=collections.defaultdict(list)
    def fetch(bundle):
        rid=str(bundle["race"]["raceId"])
        try:return rid,official_final_odds(bundle,hist,live),None
        except Exception as ex:return rid,None,str(ex)[:150]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures=[pool.submit(fetch,b) for b in candidates]
        for n,future in enumerate(concurrent.futures.as_completed(futures),start=1):
            rid,quoted,error=future.result()
            if quoted:odds[rid]=quoted
            else:
                typ=error or "NO_JRA_OFFICIAL_WIN_QUOTES"
                failures[typ]+=1
                if len(failed_rids[typ])<25:failed_rids[typ].append(rid)
            if n%100==0 or n==len(futures):
                print("POSTAUG_JRA_FINAL_ODDS_BACKFILL_PROGRESS",json.dumps({
                    "completed":n,"total":len(futures),
                    "officialFullFieldFetched":len(odds),
                    "failed":n-len(odds)}),flush=True)
    rows=[];valid=collections.Counter();bad=collections.Counter()
    for bundle in candidates:
        race=bundle["race"]
        rid=str(race["raceId"]);quotes=odds.get(rid)
        if not quotes:
            bad["missing_valid_official_final_odds"]+=1;continue
        horse=[]
        for h in bundle["runners"]:
            if h.get("runnerStatus") not in (None,"","active"):continue
            try:
                number=int(h["horseNo"])
                odd=float(quotes.get(number,0))
                age_m=re.search(r"\\d+",str(h.get("sexAge") or ""))
                age=int(age_m.group()) if age_m else 0
                weight=float(h.get("assignedWeight") or 0)
            except (ValueError,TypeError,KeyError):
                continue
            if not (1<=number<=18 and 1<=odd<=9999 and math.isfinite(odd)
                    and 0<=age<=18 and 0<=weight<=80):continue
            horse.append((number,odd,age,weight))
        horse.sort(key=lambda h:(h[1],h[0]))
        if len(horse)<10 or len({h[0] for h in horse})!=len(horse):
            bad["missing_top_ten_after_quote_validation"]+=1;continue
        venue=venue_code(race.get("venue"))
        number=int(race["raceNo"])
        if not (1<=number<=12):raise RuntimeError("INVALID_RACE_NUMBER")
        day=str(race["raceDate"])
        rows.append({"id":rid,"day":day,
            "month":day[:4]+day[5:7],
            "venue":venue,"raceNo":number,
            "horses":horse,"payout":payments[rid]})
        valid[(day,venue)]+=1
    # As with historical archive, the universe is races with >=10 quoted
    # runners and all six outcomes. A venue-day needs >=3 such races.
    all_days=set(expected)
    qualified={g for g,n in valid.items() if n>=3}
    missingdays={str(g):{"completeCashAndAtLeast10Horses":expected[g],
                         "eligibleAfterOfficialOdds":valid[g]}
                 for g in expected if g not in qualified}
    if not qualified:raise RuntimeError("NO_2026_JRA_VENUE_DATE_HAS_THREE_ELIGIBLE_RACES")
    covered=[r for r in rows if (r["day"],r["venue"]) in qualified]
    print("POSTAUG_JRA_FINAL_CASH_PROGRAM_COVERAGE",json.dumps({
       "dateWindow":[START,END],"D1Races":len(all_bundles),
       "D1Finished":count_finished,"publicSupplementedPayoutRaceCount":len(fetched),
       "completeSixMarketPayoutRaces":len(all_bundles)-len(not_confirmed),
       "genuineShortFieldRaces":len(short_field),
       "officialFullFieldQuotedRaces":len(odds),
       "historicallyComparableEligibleRaces":len(rows),
       "coveredVenueDays":len(qualified),
       "insufficientVenueDays":len(missingdays),
       "failedOfficialOdds":dict(failures.most_common(8)),
       "badAfterQuote":dict(bad),"remainingCashOrResultGaps":len(not_confirmed)
    },ensure_ascii=False),flush=True)
    return covered,{"startInclusive":START,"endExclusive":END,
      "latestRaceDate":max(r["day"] for r in rows),
      "allExistingRaceRows":len(all_bundles),
      "d1FinishedRaces":count_finished,
      "D1PreviouslyMissingCashOrFinish":len(incomplete),
      "additionalPublicSixMarketSettlementRaces":len(fetched),
      "stillMissingActualResultOrCash":len(not_confirmed),
      "publicSettlementErrorExamples":dict(list(errors.items())[:15]),
      "ineligibleUnder10Runners":len(short_field),
      "officialJraFinalOddsRaces":len(odds),
      "historicallyComparableRaces":len(rows),
      "fullVenueDaysWithMinimumThreeEligibleRaces":len(qualified),
      "venueDaysWithInsufficientEligibleRaces":len(missingdays),
      "venueDayGapDetails":missingdays,
      "excludedByQuoteIssues":dict(bad),
      "officialQuoteFetchFailures":dict(failures.most_common(8)),
      "quoteFailureRaceExamples":dict(failed_rids),
      "publicPayoutRacesCrossReconciled":True,
      "replayIncludesAllFinishedD1Races":not bool(not_confirmed or bad),
      "D1DataModified":False}

def fixed_forward_signals(base,hist,live_rows):
    # Build history feature matrix on all pre-Aug archive ONLY.
    core,historical,years,paid,cat,ticket,sig,market,ranks=hist.whole_archive_loo_scores(base)
    sparse=base.load("scripts/research-nov2026-frozen-sparse-cash-model.py","fwd_sparse_money")
    N=paid.shape[1]
    old_cache,old_race_cache=core.CACHE,core.RACE_CACHE
    try:
        core.CACHE=ROOT/"analysis-results/forward-six-market-odds-features.npz"
        core.RACE_CACHE=ROOT/"analysis-results/forward-six-market-odds-races.json"
        core.full_features(live_rows)
        with np.load(core.CACHE,allow_pickle=False) as z:
            forward_paid=z["payout"].astype(np.int32)
            forward_cat={k:z[k].astype(np.uint8) for k in sparse.FIELDS}
    finally:
        core.CACHE,core.RACE_CACHE=old_cache,old_race_cache
    if len(live_rows)!=forward_paid.shape[0]:
        raise RuntimeError("FORWARD_PAYOUT_CASH_MATRIX_MISALIGNED")
    template=np.arange(N,dtype=np.int32)[None,:]
    best=np.zeros((len(live_rows),N),dtype=np.float32)
    for i,schema in enumerate(sparse.SCHEMAS):
        codes,size=sparse.sample_group_code(cat,template,schema)
        flat=codes.ravel()
        count=np.bincount(flat,minlength=size).astype(np.float64)
        sum_pay=np.bincount(flat,weights=paid.ravel(),minlength=size)
        hits=np.bincount(flat,weights=(paid.ravel()>0),minlength=size)
        maximum=np.zeros(size,dtype=np.float64)
        wins=np.flatnonzero(paid.ravel()>0)
        np.maximum.at(maximum,flat[wins],paid.ravel()[wins])
        robust=(sum_pay-maximum)/np.maximum(count,1)
        good=(count>=13)&(hits>=2)&(robust>=200)
        rate=np.where(good,np.minimum(np.maximum(robust,0),15000)*
             np.power(np.minimum(count,200)/200,.25)*
             np.minimum(hits,15)/15,0).astype(np.float32)
        future_code,_=sparse.sample_group_code(forward_cat,template,schema)
        np.maximum(best,rate[future_code],out=best)
    _,markets=core.fixed_template()
    chosen=np.empty((len(live_rows),6),dtype=np.int16)
    strengths=np.empty((len(live_rows),6),dtype=np.float32)
    fallback=[]
    for m in range(6):
        indices=np.flatnonzero(markets==m)
        j=np.argmax(best[:,indices],axis=1)
        chosen[:,m]=indices[j]
        strengths[:,m]=best[np.arange(len(live_rows)),chosen[:,m]]
        sum_pay=paid[:,indices].astype(np.int64)
        totals=sum_pay.sum(axis=0)-sum_pay.max(axis=0)
        f=int(indices[np.argmax(totals)])
        fallback.append(f)
        chosen[:,m]=np.where(strengths[:,m]>0,chosen[:,m],f)
    print("POSTAUG_FROZEN_FULL_PERIOD_CASH_SIGNALS",json.dumps({
        "historicalRaces":len(historical),"forwardRaces":len(live_rows),
        "historicalMonthCutoff":"2026-04","historyOnlySignalLearning":True,
        "historicalLeaveOneOutTicketAlgorithm":True,
        "forwardGroupScoreFromPastOnly":True,
        "fallbackTicketIDs":fallback}),flush=True)
    return forward_paid,chosen,strengths
def ticket_replay(base,study,records,paid,chosen,signal,report):
    daygroups=base.choose_day_groups(records,np.arange(len(records),dtype=np.int32))
    patterns=dict(study.imported().proposals(base))
    out=[]
    for number,model in enumerate(report["qualifiedCandidates"][:15],start=1):
        config=model["venueQuarterDecisions"]
        bought=[]
        for day in daygroups:
            ids=np.asarray(day,dtype=np.int32)
            ref=records[int(ids[0])]
            venue=int(ref["venue"]);q=(int(ref["month"][4:])-1)//3
            sk=f"{venue}_Q{q+1}"
            if sk not in config:raise RuntimeError("MISSING_FROZEN_HIT20_VENUE_QUARTER:"+sk)
            c=config[sk]
            pair,slate,ranking=patterns[c["policy"]]
            _,bets=base.decisions(records,ids,paid,chosen,signal,
                                 [list(range(len(ids)))],pair,slate,1000,ranking,True)
            hedge=study.HEDGES[c["hedge"]]
            a=int(c["exotic1StakeYen"])
            b=int(c["exotic2StakeYen"])
            h=int(c["hedgeStakeYen"])
            if a<100 or b<0 or h!=sum(hedge)*100 or any(x%100 for x in (a,b,h)):
                 raise RuntimeError("BAD_FROZEN_HIT20_BET_STAKES")
            byid={str(records[int(i)]["id"]):int(i) for i in ids}
            for r in bets:
                j=byid.get(str(r["raceId"]))
                if j is None:raise RuntimeError("CASH_REPLAY_RACE_ID_MISMATCH")
                s1=int(paid[j,int(r["ticket1Template"])])*(a//100)
                s2=int(paid[j,int(r["ticket2Template"])])*(b//100) if b else 0
                extra=sum(int(paid[j,k])*w for k,w in zip(study.HEDGE_INDEX,hedge))
                row_paid=s1+s2+extra
                bought.append((str(r["raceId"]),row_paid,a+b+h,venue,ref["day"]))
        if len({x[0] for x in bought})!=len(bought):
             raise RuntimeError("HIT20_FORWARD_LEDGER_DUPLICATED_RACE")
        cost=sum(x[2] for x in bought)
        cash=sum(x[1] for x in bought)
        hits=sum(x[1]>0 for x in bought)
        largest=max((x[1] for x in bought),default=0)
        n=len(bought)
        forward={"races":n,"venueDays":len(daygroups),
          "stakeYen":cost,"paidYen":cash,"profitYen":cash-cost,
          "hitRaces":hits,"hitRacePct":round(100*hits/n,4) if n else None,
          "cashRoiPct":round(100*cash/cost,4) if cost else None,
          "minusLargestRaceCashRoiPct":round(100*(cash-largest)/cost,4) if cost else None,
          "maxRacePayoutYen":largest}
        out.append({"historicalCandidateNo":number,
          "historicalQualifiedMoneyAndHit":model["fullPeriodMoneyAndHits"],
          "augustOnward":forward})
        print("HIT20_ROI200_POSTAUG_OFFICIAL_REPLAY",json.dumps({
             "i":number,"past":model["fullPeriodMoneyAndHits"],
             "forward":forward},ensure_ascii=False),flush=True)
    return out

def main():
    if "--self-test" in sys.argv:
        assert venue_code("東京")==5 and venue_code("1")==1
        assert norm_nums("1-12-3")==(1,12,3)
        print("POSTAUG_CASH200_HIT20_CANDIDATE_REPLAY_SELFTEST_OK")
        return
    report=json.loads(SOURCE_RESULT.read_text(encoding="utf8"))
    patterns=report.get("qualifiedCandidates") or []
    if not patterns:raise RuntimeError("NO_HISTORICAL_HIT20_ROI200_MODEL_TO_REPLAY")
    for p in patterns:
        x=p["fullPeriodMoneyAndHits"]
        if x["cashRoiPct"]<200 or x["minusLargestRaceCashRoiPct"]<200 or x["hitRacePct"]<20:
             raise RuntimeError("INVALID_HISTORICAL_HIT20_AND_CASH200_CANDIDATE")
    records,coverage=d1_races()
    study=imp("scripts/research-20261114-roi200-hit20-full-multiticket.py","historical_robust_roi200_hit20_cash")
    full=study.imported().helper()
    base=full.load()
    paid,chosen,signal=fixed_forward_signals(base,full,records)
    analyzed=ticket_replay(base,study,records,paid,chosen,signal,report)
    result={"status":"OFFICIAL_FINAL_ODDS_RETROSPECTIVE_REPLAY_NOT_OFFICIAL_T15",
       "historicalCandidateCount":len(patterns),
       "dateRange":coverage,
       "hitDefinition":"one or more paid tickets in the selected race",
       "historicalBasis":"third party 2015-2026 Apr final win odds and settlements",
       "postAugustBasis":"JRA official historical FINAL win odds + D1 stored six-market actual payouts",
       "oddsTimestampMatchedToTrainingArchive":True,
       "provenOfficialT15BettingSimulation":False,
       "noFutureResultsUsedForProspectiveRuleSelection":True,
       "notUntouchedForwardHoldout":True,
       "allHistoricallyQualifiedCandidates":analyzed,
       "noProductionOrD1Writes":True}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("FULL_HIT20_CASH200_FORWARD_SUMMARY",json.dumps({
        "candidates":len(analyzed),"completeVenueDays":coverage["fullyRepresentedVenueDays"],
        "excludedDays":coverage["excludedPartialVenueDays"],
        "rows":[{"i":x["historicalCandidateNo"],
          "historicalHit":x["historicalQualifiedMoneyAndHit"]["hitRacePct"],
          "augRoi":x["augustOnward"]["cashRoiPct"],
          "augHit":x["augustOnward"]["hitRacePct"]} for x in analyzed]},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
