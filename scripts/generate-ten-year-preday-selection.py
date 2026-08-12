#!/usr/bin/env python3
import argparse
import collections
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CORE_PATH=ROOT/'scripts'/'ten-year-production-core.py'
COLLECTOR_PATH=ROOT/'scripts'/'collect-jra-official-odds.py'


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None: raise RuntimeError(f'MODULE_LOAD_FAILED:{path}')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--date',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    core=load(CORE_PATH,'ten_year_production_core_selection');collector=load(COLLECTOR_PATH,'ten_year_selection_collector')
    state=core.load_selection_state()
    delta=core.delta_bundles(collector,state['throughDate'],a.date)
    core.advance_selection_state(state,delta)
    targets=core.target_bundles(collector,a.date)
    if not targets: raise RuntimeError(f'TARGET_RACES_EMPTY:{a.date}')
    venue_counts=collections.Counter(str(b['race'].get('venue') or '') for b in targets)
    if '' in venue_counts or len(venue_counts)<2 or any(v!=12 for v in venue_counts.values()):
        raise RuntimeError(f'TARGET_RACE_STRUCTURE_INCOMPLETE:{dict(venue_counts)}')
    selected=core.select_target_races(state,targets,a.date)
    selected_counts=collections.Counter(str(r['venue']) for r in selected)
    if set(selected_counts)!=set(venue_counts) or any(v!=5 for v in selected_counts.values()):
        raise RuntimeError(f'CANONICAL_SELECTION_NOT_FIVE_PER_VENUE:{dict(selected_counts)}')
    payload={
        'date':a.date,
        'sourceModel':'ten-year-completed-model',
        'selectionMode':'canonical-ten-year-race-score',
        'selected':selected,
        'venueCounts':dict(venue_counts),
        'selectedVenueCounts':dict(selected_counts),
        'stateBaseThroughDate':core.load_selection_state()['throughDate'],
        'stateAdvancedThroughDate':state['throughDate'],
        'resultDataUsedForTargetDay':False,
        'historicalFinalOddsUsedForSelection':False,
        'syntheticOddsUsed':False,
    }
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'date':a.date,'selected':len(selected),'venues':dict(selected_counts),'sourceModel':payload['sourceModel']},ensure_ascii=False))


if __name__=='__main__':main()
