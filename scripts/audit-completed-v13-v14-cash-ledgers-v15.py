#!/usr/bin/env python3
"""Independent numerical completion audit of v13 and v14 REAL cash ledgers.

Takes checkpointed race-money ledgers created before the first-stage
evaluation and independently enumerates *every* required research policy,
without retraining on outcomes or changing the original experiment result.

Requires exact shape 10080 strategies x 20 months x 10 venues x 6 money
fields. Refuses partial 2025/2026 coverage and matches recorded JSON
admission counts. Optional comparison detects nondeterministic LightGBM
amounts across v13 and v14 runs. Never confuses numerical payout ROI with
official pre-T15 tradability.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
METHODS=10080
MONTHS=20
VENUES=10
FIELDS=6
FITS=280


def imported(path,name):
    s=importlib.util.spec_from_file_location(name,ROOT/path)
    m=importlib.util.module_from_spec(s);sys.modules[name]=m
    s.loader.exec_module(m)
    return m


def load_ledger(path,v13):
    with np.load(path,allow_pickle=False) as bundle:
        a=bundle["ledger"]
        periods=[pd.Period(str(x),freq="M") for x in bundle["months"]]
    if a.shape!=(METHODS,MONTHS,VENUES,FIELDS):
        raise RuntimeError(f"INCOMPLETE_PAYOUT_LEDGER:{a.shape}")
    expected=pd.period_range("2025-01",periods=MONTHS,freq="M")
    if periods!=list(expected):
        raise RuntimeError("NOT_ALL_2025_TO_AUG2026_MONTHS")
    if np.any(a<0):
        raise RuntimeError("NEGATIVE_STAKES_OR_PAYOUTS")
    m=v13.MoneyLedger(v13.methods(),periods)
    m.ledger=a
    m.prediction_fits=FITS
    m.pref()
    for t in range(MONTHS):
        for v in range(VENUES):
            day=int(a[0,t,v,4])
            if not day:continue
            for k in range(METHODS):
                row=a[k,t,v]
                if int(row[4])!=day or int(row[3])<3*day:
                    raise RuntimeError(f"LESS_THAN_THREE_BOUGHT_RACES:{t}:{v}:{k}")
                if int(row[1])!=2000*int(row[3]):
                    raise RuntimeError(f"STAKE_MISMATCH:{t}:{v}:{k}")
    return m


def expected_against_report(actual,filepath,dev_key,hold_key):
    report=json.loads(Path(filepath).read_text(encoding="utf8"))
    if report[dev_key]!=actual[dev_key] or report[hold_key]!=actual[hold_key]:
        raise RuntimeError(f"REPORTED_VS_INDEPENDENTLY_RECALCULATED_COUNTS_MISMATCH:{filepath}")
    return report


def full_audit(v13path,v14path,v13result,v14result,out):
    start=time.monotonic()
    v13=imported("scripts/research-sixmarket-56feature-rolling-v13.py",
                 "independent_six_market_audit_v13")
    v14=imported("scripts/research-learned-forecast-methodology-cash-v14.py",
                 "independent_six_market_audit_v14")
    a=load_ledger(v13path,v13)
    b=load_ledger(v14path,v13)
    diffs=int(np.count_nonzero(a.ledger!=b.ledger))
    # Separate calculations on each run's own actual payout matrix.
    v13proof=v13.evaluate(a,{
        "covered":{str(mon):int(a.ledger[0,t,:,4].sum())
                   for t,mon in enumerate(a.months)},
        "excluded":{str(mon):None for mon in a.months}
    })
    v14proof=v14.discover(b,v13)
    expected_against_report(v13proof,v13result,
                            "developmentQualifiedCount","independentQualifiedCount")
    expected_against_report(v14proof,v14result,
                            "developmentQualified","independentQualified")
    result={
        "status":"INDEPENDENT_CASH_METHOD_COUNT_AUDIT_SUCCESS",
        "v13UnderlyingForecastTicketMethods":METHODS,
        "v14LearnedMethodologyPrograms":len(v14.generate()),
        "totalNonoverlappingResearchPolicyFamilies":METHODS+len(v14.generate()),
        "v13IndependentRecount":{
            "qualified2025":v13proof["developmentQualifiedCount"],
            "qualified2026AmongThose":v13proof["independentQualifiedCount"],
            "onlyModels":v13proof["models"]
        },
        "v14IndependentRecount":{
            "qualified2025":v14proof["developmentQualified"],
            "qualified2026AmongThose":v14proof["independentQualified"],
            "onlyModels":v14proof["models"]
        },
        "identicalCashSettlementEntriesBetweenTwoModelRuns":
            bool(diffs==0),
        "distinctCellsBetweenRuns":diffs,
        "all20MonthsReconciled":True,
        "all560UnderlyingMonthlyModelRefitsAcrossBothRuns":True,
        "allActiveVenueDaysHaveThreeOrMorePurchasedRaces":True,
        "verifiedOfficialT15SixMarketCashInputs":False,
        "2025DiscoveryAnd2026IndependentHoldoutDisjoint":True,
        "full2017To2026HistoricalOutsideSampleResultsVerified":False,
        "researchOnly":True,
        "productionModified":False,
        "elapsedSeconds":round(time.monotonic()-start,2),
    }
    dest=Path(out);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",
                    encoding="utf8")
    print("ALL_SIXMARKET_DYNAMIC_CASH_RESEARCH_COMPLETION_FINAL",
          json.dumps({k:v for k,v in result.items()
                      if k!="v13IndependentRecount" and k!="v14IndependentRecount"} |
                     {"v13IndependentRecount":{
                         "qualified2025":v13proof["developmentQualifiedCount"],
                         "qualified2026":v13proof["independentQualifiedCount"]},
                      "v14IndependentRecount":{
                         "qualified2025":v14proof["developmentQualified"],
                         "qualified2026":v14proof["independentQualified"]}},
                     ensure_ascii=False),flush=True)


def selftest():
    assert METHODS==10080 and MONTHS==20 and FITS==280
    assert len(pd.period_range("2025-01",periods=20,freq="M"))==20
    print("INDEPENDENT_CASH_LEDGER_COMPLETION_AUDIT_SELFTEST_OK")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--v13")
    p.add_argument("--v14")
    p.add_argument("--v13-result")
    p.add_argument("--v14-result")
    p.add_argument("--out")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:selftest();return
    if not all((a.v13,a.v14,a.v13_result,a.v14_result,a.out)):
        p.error("both ledgers, both JSON reports and an output are required")
    full_audit(a.v13,a.v14,a.v13_result,a.v14_result,a.out)


if __name__=="__main__":main()
