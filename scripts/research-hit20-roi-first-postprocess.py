#!/usr/bin/env python3
"""Read-only ROI-first re-ranking of frozen 2024/2025 paired JRA research artifact.

No D1 reads, no model training, no data edits. 2024 selects candidates;
2025 is diagnostic only and never used to choose a candidate. Since both
years have been inspected previously, this cannot establish fresh OOS proof.
"""
import argparse,json
from pathlib import Path

def key(e):
    return tuple(e[k] for k in ("model","raceSelector","ticketPair","betType1Yen","betType2Yen","racesPerVenueDay"))

def gate(m):
    return m["hitRacePct"]>=20 and m["races"]>=100 and m["stakeYen"]==m["races"]*2000 and m["returnYen"]-m["stakeYen"]==m["netYen"]

def rank(e):
    m=e["metrics"]
    return (-m["roiMinusLargestPaidRacePct"],-m["roiPct"],-m["netYen"],key(e))

def inspect(report):
    # Requires full candidate metrics, never just the already-selected top 40.
    byyear=report["comparison"]
    if "allCandidatesByYear" in report:
        raw=report["allCandidatesByYear"]
    else:
        raise ValueError("FULL_CANDIDATE_DATA_NOT_PRESENT: regenerate research artifact with allCandidatesByYear, do not infer from top40")
    a={key(x):x for x in raw["2024"]}
    b={key(x):x for x in raw["2025"]}
    if len(a)!=len(b) or len(a)<5000 or set(a)!=set(b):raise ValueError("MISSING_OR_MISMATCHED_FULL_CANDIDATES")
    eligible=sorted((x for x in a.values() if gate(x["metrics"])),key=rank)
    if not eligible:raise ValueError("NO_2024_HIT20_ELIGIBLE_CANDIDATES")
    winner=eligible[0];k=key(winner);future=b[k]
    both=[x for x in eligible if gate(b[key(x)]["metrics"]) and
          x["metrics"]["roiPct"]>100 and b[key(x)]["metrics"]["roiPct"]>100]
    # These are diagnostic counts over the ENTIRE 12,375-policy universe, not
    # selection criteria. The 2025 outcomes were already inspected; no
    # hindsight winner is promoted as if independently selected in 2024.
    both_robust=[x for x in eligible if gate(b[key(x)]["metrics"]) and
        x["metrics"]["roiMinusLargestPaidRacePct"]>100 and
        b[key(x)]["metrics"]["roiMinusLargestPaidRacePct"]>100]
    train_profitable=[x for x in eligible if x["metrics"]["roiPct"]>100]
    year25_profitable=[x for x in eligible if gate(b[key(x)]["metrics"]) and
        b[key(x)]["metrics"]["roiPct"]>100]
    # For a fixed 2024-selected shortlist, record its 2025 performance
    # without using 2025 returns to reorder the shortlist.
    top40=eligible[:40]
    top40_positive=[x for x in top40 if gate(b[key(x)]["metrics"]) and
        b[key(x)]["metrics"]["roiPct"]>100]
    top40_robust=[x for x in top40 if gate(b[key(x)]["metrics"]) and
        b[key(x)]["metrics"]["roiMinusLargestPaidRacePct"]>100]
    for x in a.values():
        m=x["metrics"]
        if m["hitRacePct"]<20 and gate(m):
            raise AssertionError("HIT_GATE_BYPASS")
        if m["roiMinusLargestPaidRacePct"]>m["roiPct"]+0.011:
            raise ValueError("TRIMMED_ROI_EXCEEDS_RAW_ROI")
    for x in b.values():
        m=x["metrics"]
        if m["roiMinusLargestPaidRacePct"]>m["roiPct"]+0.011:
            raise ValueError("TRIMMED_ROI_EXCEEDS_RAW_ROI")
    result={"classification":"RETROSPECTIVE_ALREADY_INSPECTED_NOT_FRESH_OOS",
      "criterion":"hit >=20% each year; ROI/robust ROI first; 2024 discovery only",
      "candidateCount":len(a),"2024Hit20Count":len(eligible),
      "bothYearsHit20AndROIOver100CountDiagnosticOnly":len(both),
      "bothYearsHit20AndTrimmedROIOver100CountDiagnosticOnly":len(both_robust),
      "discovery2024ROIOver100AndHit20Count":len(train_profitable),
      "previouslyInspected2025ROIOver100AndHit20Count":len(year25_profitable),
      "frozen2024Top40Forward2025ROIOver100Count":len(top40_positive),
      "frozen2024Top40Forward2025TrimmedROIOver100Count":len(top40_robust),
      "2024FrozenBestHasRobustROIOver100":winner["metrics"]["roiMinusLargestPaidRacePct"]>100,
      "2025FrozenBestHasRobustROIOver100":future["metrics"]["roiMinusLargestPaidRacePct"]>100,
      "2024FrozenBest":{"policy":{k:v for k,v in winner.items() if k!="metrics"},
        "discovery2024":winner["metrics"],"diagnostic2025":future["metrics"]},
      "year2025NeverUsedToSelect":True,
      "winnerValidatedPositiveProfit":gate(future["metrics"]) and future["metrics"]["roiPct"]>100,
      "promoteToProduction":False,
      "limitations":["2024 and 2025 were inspected previously; not pristine holdout",
                     "archived T-15 odds not available","no per-month or venue data in summary artifact",
                     "historical 56 features not independently certified T-15 available"]}
    return result

def selftest():
    def make(i,year):
        m={"races":300,"hitRacePct":20 if i%2==0 else 19.99,
           "stakeYen":600000,"returnYen":600000+i*1000,
           "netYen":i*1000,"roiPct":100+i/6,
           "roiMinusLargestPaidRacePct":70+i/10}
        return {"model":"m"+str(i),"raceSelector":"top3","ticketPair":"x",
          "betType1Yen":200,"betType2Yen":1800,"racesPerVenueDay":3,"metrics":m}
    rows=[make(i,2024) for i in range(5000)]
    r={"comparison":{},"allCandidatesByYear":{"2024":rows,"2025":rows}}
    x=inspect(r)
    assert x["2024Hit20Count"]==2500
    assert x["2024FrozenBest"]["policy"]["model"]=="m4998"
    assert x["bothYearsHit20AndROIOver100CountDiagnosticOnly"]==2499
    assert x["bothYearsHit20AndTrimmedROIOver100CountDiagnosticOnly"]==2349
    assert x["frozen2024Top40Forward2025ROIOver100Count"]==40
    assert x["2024FrozenBestHasRobustROIOver100"] is True
    bad=json.loads(json.dumps(r));bad["allCandidatesByYear"]["2025"].pop()
    try:inspect(bad);raise AssertionError("EXPECTED_MISSING_DETECTED")
    except ValueError as e:assert "MISSING" in str(e)
    print("ROI_FIRST_HIT20_FULL_UNIVERSE_SELFTEST_OK")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--input",type=Path)
    ap.add_argument("--output",type=Path)
    args=ap.parse_args()
    if args.self_test:selftest();return
    if not args.input or not args.output:ap.error("--input and --output required")
    result=inspect(json.loads(args.input.read_text()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print("ROI_FIRST_HIT20_YEARWISE",json.dumps(result,ensure_ascii=False))

if __name__=="__main__":main()
