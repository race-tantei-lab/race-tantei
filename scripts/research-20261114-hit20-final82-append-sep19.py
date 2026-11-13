#!/usr/bin/env python3
"""Append only fully verified Sep19 Nakayama venue-day to existing 81-day cash replay.

ALL historically qualified ROI200 HIT20 portfolio decisions remain frozen 2015..2026-Apr.
Use 2026-09-19 JRA official final WIN odds for all twelve Nakayama races.
The specific valid JRA result CNAME suffix for each race was checked against
actual official JRA results pages: 1..9 (18 CD 82 37 EC A1 56 0B C0) and
10..12 (B5 6A 1F). The persisted D1 result URLs for this date are corrupt.
Actual six bet-type payouts are cross-reconciled with D1 using an independent
public completed-race archive. NO DB WRITES, no production modification.
"""
from __future__ import annotations
import collections,importlib.util,json,re,sys
from pathlib import Path
import numpy as np

R=Path(__file__).resolve().parents[1]
DATE="2026-09-19"
VENUE="中山"
OUT=R/"analysis-results/20261114-hit20-roi200-all82-venue-days-final.json"
HIST=R/"analysis-results/20261114-full-period-roi200-hit20-multiticket.json"
EIGHTY_ONE=R/"analysis-results/forward-81-venue-days/20261114-roi200-hit20-postaug-official-final-odds.json"
def imp(path,name):
    s=importlib.util.spec_from_file_location(name,R/path)
    if not s or not s.loader:raise RuntimeError("MISSING_HELPER")
    m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m);return m
def correct_official_result_url(no):
    if not 1<=no<=12:raise RuntimeError("BAD_NAKAYAMA_RACE_NUMBER")
    suffix=((0x63+0xB5*no) if no<=9 else (0xB5+0xB5*(no-10)))%256
    return (f"https://www.jra.go.jp/JRADB/accessS.html?CNAME="
            f"pw01sde010620260405{no:02d}20260919/{suffix:02X}")
def build():
    live=imp("scripts/postaug-support-aug-nov-frozen-policy-recheck.py","d1_sep19_append")
    forward=imp("scripts/research-20261114-hit20-official-final-forward.py","cash_sep19_replay")
    official=imp("scripts/research-enrich-official-history-odds.py","official_final_race_reader")
    pub=imp("scripts/research-20261114-public-results-six-payout-fallback.py","public_actual_race_cash")
    races=live.d1_query("""SELECT race_id raceId,race_date raceDate,venue,
        race_no raceNo,meeting_no meetingNo,meeting_day meetingDay,result_url resultUrl,status
        FROM rt_races WHERE race_date=? AND venue=?
        ORDER BY race_no LIMIT 20""",[DATE,VENUE])
    if len(races)!=12 or sorted(int(r["raceNo"]) for r in races)!=list(range(1,13)):
        raise RuntimeError("SEPTEMBER_19_FULL_NAKAYAMA_PROGRAM_NOT_AVAILABLE")
    runners=live.d1_query("""SELECT race_id raceId,horse_no horseNo,sex_age sexAge,
        assigned_weight assignedWeight,runner_status runnerStatus
        FROM rt_runners WHERE race_id LIKE ?
        ORDER BY race_id,horse_no LIMIT 250""",[DATE+"-nakayama-%"])
    if len(runners)<100:raise RuntimeError("SEPTEMBER_19_NAKAYAMA_RUNNERS_MISSING")
    by_race=collections.defaultdict(list)
    for r in runners:by_race[str(r["raceId"])].append(r)
    TYPES=pub.TYPES
    payments=live.d1_query("""SELECT race_id raceId,bet_type betType,
        combination,payout_yen payoutYen FROM rt_payouts
        WHERE race_id LIKE ? ORDER BY race_id,bet_type,combination LIMIT 200""",
        [DATE+"-nakayama-%"])
    d1p=collections.defaultdict(lambda:[{} for _ in TYPES])
    for row in payments:
        m=TYPES.index(row["betType"])
        key=tuple(int(x) for x in re.findall(r"[0-9]+",str(row["combination"])))
        if TYPES[m] in pub.UNORDERED:key=tuple(sorted(key))
        money=int(row["payoutYen"])
        if key in d1p[row["raceId"]][m] and d1p[row["raceId"]][m][key]!=money:
            raise RuntimeError("CONFLICT_D1_SEPTEMBER_19_PAY")
        d1p[row["raceId"]][m][key]=money
    rows=[];checks=[]
    for r in races:
        no=int(r["raceNo"])
        raceid=str(r["raceId"])
        url=correct_official_result_url(no)
        active=[h for h in by_race[raceid] if h.get("runnerStatus") in (None,"","active")]
        # Exactly as the original 2015-26 archive: fewer than 10 runners
        # are not bettable under this pre-existing top-ten strategy.
        if len({int(h["horseNo"]) for h in active})<10:
            checks.append({"raceId":raceid,"raceNo":no,
                "officialResultUrl":url,"originalD1Status":r["status"],
                "actualActiveRunners":len(active),"historicalRuleEligible":False,
                "reason":"GENUINE_FIELD_UNDER_TEN_HORSES"})
            print("SEPTEMBER_19_NAKAYAMA_JRA_RACE_INELIGIBLE",
                  json.dumps(checks[-1],ensure_ascii=False),flush=True)
            continue
        bundle={"race":{**r,"resultUrl":url},"runners":by_race[raceid]}
        quotes=forward.official_final_odds(bundle,official,live)
        public,provenance=pub.fetch_public(r)
        reconciled=pub.integrate(d1p[raceid],public,raceid)
        horses=[]
        for h in by_race[raceid]:
            if h.get("runnerStatus") not in (None,"","active"):continue
            number=int(h["horseNo"])
            if number not in quotes:continue
            odd=float(quotes[number])
            age_match=re.search(r"[0-9]+",str(h.get("sexAge") or ""))
            age=int(age_match.group()) if age_match else 0
            weight=float(h.get("assignedWeight") or 0)
            if 1<=number<=18 and 1<=odd<=9999 and 0<=age<=18 and 0<=weight<=80:
                horses.append((number,odd,age,weight))
        horses.sort(key=lambda x:(x[1],x[0]))
        accepted=len(horses)>=10 and len({x[0] for x in horses})==len(horses)
        checks.append({"raceId":raceid,"raceNo":no,"officialResultUrl":url,
           "officialOddsHorseCount":len(quotes),"originalD1Status":r["status"],
           "JraSource":True,"sixMarketPayoutsReconciled":True,
           "publicResultSource":provenance["url"],"historicalRuleEligible":accepted})
        if accepted:
            rows.append({"id":raceid,"day":DATE,"month":"202609",
                "venue":6,"raceNo":no,"horses":horses,"payout":reconciled})
        print("SEPTEMBER_19_NAKAYAMA_JRA_RACE_VERIFIED",json.dumps(checks[-1],ensure_ascii=False),flush=True)
    if len(rows)<3:raise RuntimeError("SEPTEMBER_19_FEWER_THAN_THREE_ELIGIBLE")
    return rows,checks
def main():
    if "--self-test" in sys.argv:
        assert correct_official_result_url(1).endswith("/18")
        assert correct_official_result_url(7).endswith("/56")
        assert correct_official_result_url(10).endswith("/B5")
        assert correct_official_result_url(11).endswith("/6A")
        assert correct_official_result_url(12).endswith("/1F")
        print("SEPTEMBER_19_OFFICIAL_CNAME_SELFTEST_OK",flush=True);return
    original=json.loads(EIGHTY_ONE.read_text(encoding="utf8"))
    patterns=json.loads(HIST.read_text(encoding="utf8"))
    if len(original["allHistoricallyQualifiedCandidates"])!=15 or len(patterns["qualifiedCandidates"])!=15:
        raise RuntimeError("ALL_15_FROZEN_CASH200_HIT20_CANDIDATES_NOT_AVAILABLE")
    rows,checks=build()
    study=imp("scripts/research-20261114-roi200-hit20-full-multiticket.py","original_frozen_cash_study")
    forward=imp("scripts/research-20261114-hit20-official-final-forward.py","replay_sep19_2026_official")
    full=study.imported().helper();base=full.load()
    paid,chosen,signal=forward.fixed_forward_signals(base,full,rows)
    daily=forward.ticket_replay(base,study,rows,paid,chosen,signal,patterns)
    out=[]
    for orig,extra in zip(original["allHistoricallyQualifiedCandidates"],daily):
        if orig["historicalCandidateNo"]!=extra["historicalCandidateNo"]:raise RuntimeError("CANDIDATE_ORDER_CHANGED")
        if orig["historicalQualifiedMoneyAndHit"]!=extra["historicalQualifiedMoneyAndHit"]:raise RuntimeError("HISTORIC_LOCK_MISMATCH")
        first=orig["augustOnward"];day=extra["augustOnward"]
        stake=first["stakeYen"]+day["stakeYen"]
        cash=first["paidYen"]+day["paidYen"]
        hits=first["hitRaces"]+day["hitRaces"]
        races_n=first["races"]+day["races"]
        maxrace=max(first["maxRacePayoutYen"],day["maxRacePayoutYen"])
        summary={"races":races_n,"venueDays":first["venueDays"]+day["venueDays"],
          "stakeYen":stake,"paidYen":cash,"profitYen":cash-stake,
          "hitRaces":hits,"hitRacePct":round(hits*100/races_n,4),
          "cashRoiPct":round(cash*100/stake,4),
          "minusLargestRaceCashRoiPct":round((cash-maxrace)*100/stake,4),
          "maxRacePayoutYen":maxrace}
        if summary["venueDays"]!=82 or day["venueDays"]!=1 or day["races"]<3:
            raise RuntimeError("APPENDED_DAY_COVERAGE_INVALID")
        out.append({"candidateNo":orig["historicalCandidateNo"],
           "historical2015To2026Apr":orig["historicalQualifiedMoneyAndHit"],
           "fromPreviouslyValidated81VenueDays":first,
           "newlyRecoveredNakayamaSep19":day,
           "all82VenueDaysAug1ToNov13":summary})
        print("HIT20_ROI200_CASH_82_VENUE_DAYS",json.dumps({"candidateNo":orig["candidateNo"],
           **summary},ensure_ascii=False),flush=True)
    report={"status":"ALL_82_REAL_VENUE_DAYS_2026_AUG_NOV_HIT20_CASH200_FROZEN_REPLAY_DONE",
      "fullyVerifiedVenueDays":82,"originalD1BadResultUrlsReplacedOnlyInMemory":True,
      "JraOfficialFinalOddsNotT15":True,"preRaceTradabilityVerified":False,
      "historicalPatternsFrozenBefore2026Aug":True,
      "JraResultsSourceUrlMethod":"exact Sep19 Nakayama official CNAME checked for all 12 races",
      "nonOfficialThirdPartyPayoutCrossCheckedAgainstD1":True,
      "other81VenueDaySource":"https://github.com/race-tantei-lab/race-tantei/actions/runs/43521794364",
      "september19Checks":checks,"results":out,
      "noD1Writes":True,"noProductionChange":True,
      "selectionStillUsesOnlyAvailableHistoricallyComparableFullFieldRaceCandidates":True}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("HIT20_ROI200_2026_AUG_NOV_ALL_82_VENUE_DAYS_FINAL",
          json.dumps({"status":report["status"],"results":[{
            "no":x["candidateNo"],
            "races":x["all82VenueDaysAug1ToNov13"]["races"],
            "cashRoiPct":x["all82VenueDaysAug1ToNov13"]["cashRoiPct"],
            "hitRacePct":x["all82VenueDaysAug1ToNov13"]["hitRacePct"]}
            for x in out]},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
