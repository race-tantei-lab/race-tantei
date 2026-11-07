#!/usr/bin/env python3
"""Read-only research-only D1 coverage audit. Does not train or deploy any model."""
import json,os,urllib.request

A=os.environ["CLOUDFLARE_ACCOUNT_ID"]
D=os.environ["CLOUDFLARE_D1_DATABASE_ID"]
T=os.environ["CLOUDFLARE_API_TOKEN"]
U=f"https://api.cloudflare.com/client/v4/accounts/{A}/d1/database/{D}/query"

def query(sql,params=()):
    request=urllib.request.Request(U,data=json.dumps({"sql":sql,"params":list(params)}).encode(),method="POST",headers={"Authorization":"Bearer "+T,"Content-Type":"application/json"})
    with urllib.request.urlopen(request,timeout=60) as response: x=json.load(response)
    if not x.get("success"):raise RuntimeError(str(x.get("errors"))[:450])
    return (x.get("result") or [{}])[0].get("results") or []

def main():
    out={}
    table_cols={
        "rt_official_value_candidates":"captured_at_utc",
        "rt_official_odds_snapshots":"captured_at_utc",
    }
    for table,col in table_cols.items():
        out[table]={}
        for start,end in (("2024-01-01","2025-01-01"),("2025-01-01","2026-01-01"),
                          ("2026-01-01","2026-08-10"),("2026-08-10","2026-11-08")):
            try:
                result=query(f"""SELECT COUNT(*) AS rows, COUNT(DISTINCT race_id) AS races,
                    MIN({col}) AS oldestCapture, MAX({col}) AS latestCapture
                    FROM {table} WHERE race_id>=? AND race_id<?""",(start+"-",end+"-"))
                out[table][start+".."+end]=result[0] if result else {}
            except Exception as e:
                out[table][start+".."+end]={"error":str(e)[:350]}
    for table in ("rt_races","rt_payouts"):
        out[table]={}
        for start,end in (("2024-01-01","2025-01-01"),("2025-01-01","2026-01-01"),
                          ("2026-01-01","2026-08-10"),("2026-08-10","2026-11-08")):
            try:
                result=query(f"""SELECT COUNT(*) AS rows,COUNT(DISTINCT race_id) AS races
                  FROM {table} WHERE race_id>=? AND race_id<?""",(start+"-",end+"-"))
                out[table][start+".."+end]=result[0] if result else {}
            except Exception as e:
                out[table][start+".."+end]={"error":str(e)[:350]}
    # Join the historical live winners to stored JRA payouts: a required
    # precondition for any future shadow-combination comparison.
    paid=query("""
      SELECT b.race_id AS raceId,b.bet_type AS betType,b.combination,
        b.stake_yen AS stakeYen,b.return_yen AS returnYen,
        MAX(p.payout_yen) AS payout100,
        r.refund_horse_nos_json AS refundHorses
      FROM rt_public_bets b
      JOIN rt_races r ON r.race_id=b.race_id
      LEFT JOIN rt_payouts p ON p.race_id=b.race_id
        AND p.bet_type=b.bet_type AND p.combination=b.combination
      WHERE b.race_id>=? AND b.race_id<?
        AND b.course='ライト' AND b.source_prediction_id=-2
        AND b.settlement_status='settled'
        AND b.return_yen>0
      GROUP BY b.id ORDER BY b.race_id,b.id LIMIT 500
    """,("2026-08-10-","2026-11-08-"))
    okay=0;refunds=0;mismatches=[]
    for row in paid:
        stake=int(row["stakeYen"])
        returned=int(row["returnYen"])
        payout=row.get("payout100")
        if payout is not None and int(payout)*stake//100 == returned:
            okay+=1;continue
        cancelled={int(x) for x in json.loads(row.get("refundHorses") or "[]")}
        numbers={int(v) for v in row["combination"].split("-")}
        if numbers & cancelled and stake==returned:
            refunds+=1;continue
        mismatches.append({"raceId":row["raceId"],"betType":row["betType"],"combination":row["combination"],"payout100":payout,"stakeYen":stake,"returnYen":returned})
    out["positiveProductionTicketPayoutJoin"]={
        "positiveTickets":len(paid),"exactMatched":okay,"correctlyRefunded":refunds,
        "mismatchCount":len(mismatches),"firstMismatches":mismatches[:8],
        "warning":"stored D1 JRA data, not independent website verification"
    }
    print("RESEARCH_HISTORICAL_TICKET_OFFICIAL_ODDS_COVERAGE",json.dumps(out,ensure_ascii=False,separators=(",",":")))

if __name__=="__main__":main()
