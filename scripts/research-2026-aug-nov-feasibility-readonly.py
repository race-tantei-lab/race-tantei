#!/usr/bin/env python3
"""Read-only feasibility check for an honest 2026 Aug-Nov retrospective proxy.
No D1 writes, no public ticket changes, no heavy market-odds exports.
"""
from __future__ import annotations
import json,os,urllib.request
API=f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}/d1/database/{os.environ['CLOUDFLARE_D1_DATABASE_ID']}/query"
def query(sql,params):
    req=urllib.request.Request(API,method="POST",data=json.dumps({"sql":sql,"params":params}).encode(),
      headers={"Authorization":"Bearer "+os.environ["CLOUDFLARE_API_TOKEN"],"Content-Type":"application/json"})
    try:
      with urllib.request.urlopen(req,timeout=60) as resp:j=json.loads(resp.read())
      if not j.get("success"):raise RuntimeError("D1_SQL_FAILED "+str(j.get("errors"))[:350])
      return (j.get("result") or [{}])[0].get("results") or []
    except Exception as e:
      raise RuntimeError("D1_QUERY_NOT_ACCESSIBLE: "+str(e)[:350]) from None
def main():
  start,end="2026-08-10","2026-11-08"
  races=query("""SELECT substr(race_date,1,7) month,count(*) races,
    sum(CASE WHEN status='finished' THEN 1 ELSE 0 END) finished,
    sum(CASE WHEN status!='finished' THEN 1 ELSE 0 END) unfinished
    FROM rt_races WHERE race_date>=? AND race_date<? GROUP BY 1 ORDER BY 1""",[start,end])
  runners=query("""SELECT substr(race_id,1,7) month,count(*) runnerRows,
    count(DISTINCT race_id) racesRepresented,
    sum(CASE WHEN win_odds>=10 AND win_odds<=30 THEN 1 ELSE 0 END) withinOddsBand,
    sum(CASE WHEN win_odds IS NOT NULL THEN 1 ELSE 0 END) withWinOdds,
    sum(CASE WHEN runner_status='active' THEN 1 ELSE 0 END) active
    FROM rt_runners WHERE race_id>=? AND race_id<?
    GROUP BY 1 ORDER BY 1""",[start+"-",end+"-"])
  results=query("""SELECT substr(race_id,1,7) month,
    count(*) resultRows,count(DISTINCT race_id) racesRepresented,
    sum(CASE WHEN finish_position=1 THEN 1 ELSE 0 END) winRows
    FROM rt_results WHERE race_id>=? AND race_id<?
    GROUP BY 1 ORDER BY 1""",[start+"-",end+"-"])
  # The archived live odds snapshot table may cover selected races only.
  # Count T-15 source rows to distinguish missing runner win odds from
  # any independently preserved pre-race quotes. Bounded by race_id range.
  snapshots=query("""SELECT substr(race_id,1,7) month,
    count(*) preT15WinQuoteRows,count(DISTINCT race_id) preT15WinQuoteRaces
    FROM rt_official_odds_snapshots
    WHERE race_id>=? AND race_id<? AND bet_type='単勝'
      AND odds_source='jra_official' AND seconds_to_start>=900
    GROUP BY 1 ORDER BY 1""",[start+"-",end+"-"])
  print("AUG_NOV_RETROSPECTIVE_FEASIBILITY",json.dumps({"races":races,"runners":runners,"results":results,"preT15WinSnapshots":snapshots,
    "limitation":"end-of-day or final win odds unverified for T-15; unknown complete prior-runner continuity; no counterfactual ROI yet",
    "allReadOnly":True},ensure_ascii=False))
if __name__=="__main__":main()
