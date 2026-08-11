#!/usr/bin/env python3
import argparse,json
from pathlib import Path

BUDGETS={'ライト':2000,'スタンダード':5000,'プレミアム':10000}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    p=Path(a.input);m=json.loads(p.read_text())
    robust=[]
    for key,v in m['variants'].items():
        ex={}
        for c,x in v['courses'].items():
            largest=int((x.get('returnConcentration') or {}).get('largestRaceReturnYen') or 0)
            stake=int(x.get('stakeYen') or 0);ret=int(x.get('returnYen') or 0);budget=BUDGETS[c]
            ex[c]=round(100*(ret-largest)/(stake-budget),4) if stake>budget else None
            x['roiExLargestRacePct']=ex[c]
        complete=bool(v.get('completeOddsAndEvaluation'))
        raw200=complete and all((v['courses'][c].get('roiPct') or 0)>=200 for c in BUDGETS)
        ex100=complete and all((ex[c] or 0)>=100 for c in BUDGETS)
        v['allThreeObservedAtLeast200Pct']=raw200
        v['allThreeExLargestRaceAtLeast100Pct']=ex100
        v['completionGatePassed']=bool(raw200 and ex100)
        robust.append((v['completionGatePassed'],min(ex[c] or 0 for c in BUDGETS),min(v['courses'][c].get('roiPct') or 0 for c in BUDGETS),key))
    robust.sort(reverse=True)
    m['completionPolicy']={'allThreeObservedRoiAtLeastPct':200,'allThreeRoiAfterRemovingLargestRaceAtLeastPct':100,'requiresCompleteOddsAndEvaluation':True,'historicalFinalOddsStillRequiresSeparatePrestartTimingValidation':True}
    m['robustRanking']=[x[3] for x in robust]
    m['bestRobustVariant']=m['robustRanking'][0] if robust else None
    b=m['bestRobustVariant'];m['completionGatePassed']=bool(b and m['variants'][b]['completionGatePassed'])
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'bestRobustVariant':b,'completionGatePassed':m['completionGatePassed'],'rawRoi':{c:m['variants'][b]['courses'][c]['roiPct'] for c in BUDGETS} if b else None,'exLargestRoi':{c:m['variants'][b]['courses'][c]['roiExLargestRacePct'] for c in BUDGETS} if b else None},ensure_ascii=False))
if __name__=='__main__':main()
