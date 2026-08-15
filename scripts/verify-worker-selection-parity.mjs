import fs from 'node:fs';
import zlib from 'node:zlib';
import { hydrateCompletedSelectionState, selectCompletedTargetRaces } from '../dist-selection-parity/completed-selection-runtime.js';

const stateRaw=JSON.parse(zlib.gunzipSync(fs.readFileSync('models/ten-year-race-selection-state.json.gz')).toString('utf8'));
const bundles=JSON.parse(fs.readFileSync('/tmp/selection-target-bundles.json','utf8'));
const expected=JSON.parse(fs.readFileSync('/tmp/selection-python.json','utf8'));
const state=hydrateCompletedSelectionState(stateRaw);
const actual=selectCompletedTargetRaces(state,bundles,expected.date);
const actualIds=actual.map(x=>x.raceId);
const expectedIds=expected.selected.map(x=>x.raceId);
if(JSON.stringify(actualIds)!==JSON.stringify(expectedIds)){
  console.error(JSON.stringify({status:'SELECTION_PARITY_MISMATCH',expectedIds,actualIds,actual},null,2));
  process.exit(1);
}
console.log(JSON.stringify({status:'SELECTION_PARITY_OK',date:expected.date,selectedRaceCount:actual.length,selectedRaceIds:actualIds},null,2));
