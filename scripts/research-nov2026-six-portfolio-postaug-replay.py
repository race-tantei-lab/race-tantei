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
SOURCE_RESULT=ROOT/"analysis-results/nov2026-full-cash-free-stake-roi200-only.json"
OUT=ROOT/"analysis-results/nov2026-six-roi200-candidates-postaug-audit.json"
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
def reconstruct_official_pc_result_urls(bundles):
    """Reconstruct same-race JRA URL from verified, finished neighbor CNAMEs.

    CNAME byte relation was independently verified against JRA official
    result pages on Sep19 Nakayama races 1-12 and Sep22 Nakayama 9-12.
    Do not generalize without a same-date / same-venue / same-meeting
    authentic finished-results CNAME anchor.
    """
    from collections import defaultdict, Counter
    def offset(no):
        if no<=9:return ((no-1)*0xB5)&255
        return (8*0xB5-0x0B+(no-10)*0xB5)&255
    regex=re.compile(
      r"pw01sde01([0-9]{2})([0-9]{4})([0-9]{2})([0-9]{2})"
      r"([0-9]{2})([0-9]{8})/([0-9A-Fa-f]{2})",re.I)
    keys={}
    anchors=defaultdict(list)
    for b in bundles:
        race=b["race"]
        day=str(race["raceDate"])
        code=venue_code(race["venue"])
        meet=int(race["meetingNo"]);meet_day=int(race["meetingDay"])
        key=(day,code,meet,meet_day)
        keys[str(race["raceId"])]=(key,int(race["raceNo"]))
        if race.get("status")!="finished":continue
        raw=urllib.parse.unquote(str(race.get("resultUrl") or ""))
        m=regex.search(raw)
        if not m:continue
        v,year,mm,dd,no,ymd,suffix=m.groups()
        if (int(v)!=code or int(year)!=int(day[:4])
           or int(mm)!=meet or int(dd)!=meet_day
           or int(no)!=int(race["raceNo"]) or ymd!=day.replace("-","")):
            continue
        anchors[key].append((int(no),(int(suffix,16)-offset(int(no)))%256))
    bases={}
    rejected=0
    for key,rows in anchors.items():
        votes=Counter(base for _,base in rows)
        best,n=votes.most_common(1)[0]
        if n < max(1,(len(rows)+1)//2):
           rejected+=1
           continue
        bases[key]=best
    recovered={}
    for rid,(key,rno) in keys.items():
        if key not in bases:continue
        day,v,m,d=key
        cs=(bases[key]+offset(rno))&255
        cname=(f"pw01sde01{v:02d}{day[:4]}{m:02d}{d:02d}"
               f"{rno:02d}{day.replace('-','')}/{cs:02X}")
        recovered[rid]="https://www.jra.go.jp/JRADB/accessS.html?CNAME="+cname
    print("JRA_FINAL_OFFICIAL_CNAME_RECOVERY_MAP",json.dumps({
        "allRaceRows":len(bundles),"validSameDateVenueGroups":len(bases),
        "recoveredCandidateUrls":len(recovered),
        "ambiguousGroupsRejected":rejected,
        "usesOnlyFinishedJraSameDateAnchor":True},ensure_ascii=False),flush=True)
    return recovered

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
    substitute=reconstruct_official_pc_result_urls(all_bundles)
    repaired=[]
    def fetch(bundle):
        rid=str(bundle["race"]["raceId"])
        try:return rid,official_final_odds(bundle,hist,live),None,False
        except Exception as original_error:
            if rid in substitute:
                alt={"race":{**bundle["race"],"resultUrl":substitute[rid]},
                     "runners":bundle["runners"]}
                try:return rid,official_final_odds(alt,hist,live),None,True
                except Exception as ex:
                    return rid,None,(str(original_error)[:90]+
                         " -> recovered:"+str(ex)[:70]),False
            return rid,None,str(original_error)[:150],False
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures=[pool.submit(fetch,b) for b in candidates]
        for n,future in enumerate(concurrent.futures.as_completed(futures),start=1):
            rid,quoted,error,was_recovered=future.result()
            if quoted:
                odds[rid]=quoted
                if was_recovered:repaired.append(rid)
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
       "officialFullFieldRowsRecoveredFromVerifiedCname":len(repaired),
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
      "officialJraResultUrlsReconstructedFromValidAnchors":len(repaired),
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
    policy=dict(study.proposals(base))
    out=[]
    for number,model in enumerate(report["bestCash200Patterns"],start=1):
        config=model["venueQuarterDecisions"]
        selected=[]
        for day in daygroups:
            # Every venue-day belongs to exactly one venue/quarter.
            ids=np.asarray(day,dtype=np.int32)
            ref=records[int(ids[0])]
            venue=int(ref["venue"]);q=(int(ref["month"][4:])-1)//3
            sk=f"{venue}_Q{q+1}"
            if sk not in config:
                raise RuntimeError("MISSING_FROZEN_VENUE_QUARTER_CONFIG:"+sk)
            c=config[sk]
            pair,slate,ranking=policy[c["policy"]]
            _,bets=base.decisions(records,ids,paid,chosen,signal,[list(range(len(ids)))],
                                  pair,slate,1000,ranking,True)
            for r in bets:
                ix=next((int(i) for i in ids if str(records[int(i)]["id"])==str(r["raceId"])),None)
                if ix is None:raise RuntimeError("RACE_ALIGNMENT_MISMATCH")
                a=int(c["stake1Yen"]);b=int(c["stake2Yen"])
                if a<100 or b<0 or a%100 or b%100:
                    raise RuntimeError("INVALID_FROZEN_CASH_STAKE")
                one=int(paid[ix,int(r["ticket1Template"])])
                two=int(paid[ix,int(r["ticket2Template"])]) if b else 0
                rowpaid=one*(a//100)+two*(b//100)
                selected.append((str(r["raceId"]),rowpaid,a+b,venue,ref["day"]))
        bought=[v[0] for v in selected]
        if len(set(bought))!=len(bought):
            raise RuntimeError("REPLAY_DUPLICATED_BET_RACE")
        cost=sum(v[2] for v in selected);cash=sum(v[1] for v in selected)
        hits=sum(v[1]>0 for v in selected);maxpay=max((v[1] for v in selected),default=0)
        n=len(selected)
        m={"races":n,"venueDays":len(daygroups),
           "stakeYen":cost,"paidYen":cash,"profitYen":cash-cost,
           "hitRaces":hits,"hitRacePct":round(hits*100/n,4) if n else None,
           "cashRoiPct":round(cash*100/cost,4) if cost else None,
           "minusLargestRaceCashRoiPct":round((cash-maxpay)*100/cost,4) if cost else None,
           "maxRacePayoutYen":maxpay}
        out.append({"candidateNo":number,
           "historyCandidateMethod":model["method"],
           "historicalCash":model["fullPeriodCash"],
           "augustOnward":m})
        print("SIX_ROI200_HIT_AND_POSTAUG",json.dumps({
            "candidateNo":number,
            "fullPeriodHitPct":model["fullPeriodCash"]["hitRacePct"],
            "forwardHitPct":m["hitRacePct"],"forwardRoiPct":m["cashRoiPct"],
            "forwardBets":n,"forwardStake":cost,"forwardPaid":cash},ensure_ascii=False),flush=True)
    return out
def main():
    if "--self-test" in sys.argv:
        assert venue_code("東京")==5 and venue_code("1")==1
        assert norm_nums("1-12-3")==(1,12,3)
        print("POSTAUG_SIX_CANDIDATE_REPLAY_SELFTEST_OK")
        return
    report=json.loads(SOURCE_RESULT.read_text(encoding="utf8"))
    patterns=report.get("bestCash200Patterns") or []
    if len(patterns)!=6:
        raise RuntimeError("HISTORICAL_SIX_CANDIDATES_MISSING:"+str(len(patterns)))
    for p in patterns:
        x=p["fullPeriodCash"]
        if x["cashRoiPct"]<200 or x["minusLargestRaceCashRoiPct"]<200:
            raise RuntimeError("BELOW200_ENTERED_CANDIDATE_LIST")
        if x.get("hitRaces") is None:
            raise RuntimeError("HISTORICAL_SAME_BETS_HIT_COUNTS_MISSING")
    records,coverage=d1_races()
    study=imp("scripts/research-nov2026-full-history-free-stake-roi200.py","historical_six_fixed_policies")
    full=study.helper()
    base=full.load()
    paid,chosen,signal=fixed_forward_signals(base,full,records)
    analyzed=ticket_replay(base,study,records,paid,chosen,signal,report)
    result={"status":"OFFICIAL_FINAL_ODDS_RETROSPECTIVE_REPLAY_NOT_OFFICIAL_T15",
       "historicalCandidateCount":len(patterns),
       "dateRange":coverage,
       "hitDefinition":"one or more paid tickets in the selected race",
       "historicalBasis":"third party 2015-2026 Apr final win odds and settlements",
       "postAugustBasis":"JRA official historical final win odds with D1 six-market payout and independently cross-checked public-results supplements",
       "oddsTimestampMatchedToTrainingArchive":False,
       "provenOfficialT15BettingSimulation":False,
       "oddsMoment":"JRA official historical final odds, not pre-race T-15",
       "noFutureResultsUsedForProspectiveRuleSelection":True,
       "notUntouchedForwardHoldout":True,
       "allSixCandidates":analyzed,
       "noProductionOrD1Writes":True}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("SIX_ROI200_FULL_REPLAY_SUMMARY",json.dumps({
        "candidates":len(analyzed),"completeVenueDays":coverage["fullyRepresentedVenueDays"],
        "excludedDays":coverage["excludedPartialVenueDays"],
        "rows":[{"i":x["candidateNo"],
          "historicalHit":x["historicalCash"]["hitRacePct"],
          "augRoi":x["augustOnward"]["cashRoiPct"],
          "augHit":x["augustOnward"]["hitRacePct"]} for x in analyzed]},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
