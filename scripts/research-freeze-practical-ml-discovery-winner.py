#!/usr/bin/env python3
import argparse,json
from pathlib import Path

PRACTICAL_SELECTORS={'confidence','concentration'}
COURSES=('light','standard','premium')

def rank_key(x):
    return (
        min(x['courses'][c]['top50ExcludedRoiPct'] for c in COURSES),
        min(x['courses'][c]['top100ExcludedRoiPct'] for c in COURSES),
        min(x['courses'][c]['top1PctExcludedRoiPct'] for c in COURSES),
        min(x['courses'][c]['roiPct'] for c in COURSES),
    )

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    d=json.loads(Path(a.input).read_text(encoding='utf-8'))
    combos=d['combinations']
    practical={k:v for k,v in combos.items() if v['selector'] in PRACTICAL_SELECTORS and not v.get('selectorUsesHistoricalFinalPopularity',False)}
    if len(practical)!=8:raise RuntimeError(f'PRACTICAL_COMBO_COUNT_INVALID:{len(practical)}')
    key=max(practical,key=lambda k:(rank_key(practical[k]),k));w=practical[key]
    top50={c:w['courses'][c]['top50ExcludedRoiPct'] for c in COURSES}
    top100={c:w['courses'][c]['top100ExcludedRoiPct'] for c in COURSES}
    top1pct={c:w['courses'][c]['top1PctExcludedRoiPct'] for c in COURSES}
    overall={c:w['courses'][c]['roiPct'] for c in COURSES}
    practical_winner={
      'key':key,'selector':w['selector'],'template':w['template'],
      'top50ExcludedRoiPct':top50,'top100ExcludedRoiPct':top100,'top1PctExcludedRoiPct':top1pct,'overallRoiPct':overall,
      'minTop50ExcludedRoiPct':min(top50.values()),'minTop100ExcludedRoiPct':min(top100.values()),'minTop1PctExcludedRoiPct':min(top1pct.values()),'minOverallRoiPct':min(overall.values()),
      'historicalFinalPopularityUsedForSelection':False,
      'eligibleForHistoricalHoldout':all(v>=200.0 for v in top50.values()),
      'holdoutEligibilityRule':'all three courses must have Top50-excluded ROI >= 200% on 2016-2022 discovery',
    }
    d['practicalCandidatePool']={'selectors':sorted(PRACTICAL_SELECTORS),'candidateCombinations':len(practical),'historicalFinalPopularityAllowed':False}
    d['practicalDiscoveryWinner']=practical_winner
    d['historicalHoldoutMayBeOpened']=practical_winner['eligibleForHistoricalHoldout']
    d['historicalHoldoutOpeningPolicy']='Do not fetch or evaluate 2023-2026 for this candidate unless practicalDiscoveryWinner is eligibleForHistoricalHoldout.'
    Path(a.out).parent.mkdir(parents=True,exist_ok=True);Path(a.out).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(practical_winner,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
