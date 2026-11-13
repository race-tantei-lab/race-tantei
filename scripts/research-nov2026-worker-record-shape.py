#!/usr/bin/env python3
"""Audit original frozen Worker metadata fields, no raw horse/payment dump."""
import importlib.util,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("t15_shape",ROOT/"scripts/research-nov2026-worker-freeze-t15-coverage.py")
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
def run():
  if "--self-test" in sys.argv:
    assert len("worker_live_final:")==18
    print("WORKER_PROVENANCE_FIELDS_SELFTEST_OK");return
  out={}
  for month in ("08","09","10","11"):
    lo=f"worker_live_final:2026-{month}-01-"
    # End on first day next month.
    hi=(f"worker_live_final:2026-{int(month)+1:02d}-01-"
        if int(month)<11 else "worker_live_final:2026-12-01-")
    rows=m.q("SELECT state_key AS stateKey,state_value AS stateValue "
              "FROM rt_system_state WHERE state_key>=? AND state_key<? "
              "ORDER BY state_key DESC LIMIT 3",[lo,hi])
    summaries=[]
    for row in rows:
      raw=json.loads(row["stateValue"])
      shapes={}
      for k,v in raw.items():
        if isinstance(v,list):shapes[k]={"type":"list","length":len(v)}
        elif isinstance(v,dict):shapes[k]={"type":"object","keys":sorted(v)[:25]}
        else:shapes[k]={"type":type(v).__name__}
      summaries.append({"raceId":row["stateKey"].removeprefix("worker_live_final:"),
                        "shapes":shapes})
    out[month]=summaries
  report={"researchOnly":True,"noWrites":True,"fieldsByMonth":out}
  p=Path("analysis-results/nov2026-worker-record-available-fields.json")
  p.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
  print("ORIGINAL_SAVED_BET_FIELD_SHAPES",json.dumps(report,ensure_ascii=False),flush=True)
if __name__=="__main__":run()
