#!/usr/bin/env python3
import gzip,json,base64,glob,os
from pathlib import Path
root=Path(__file__).resolve().parents[1]
print('ARCHIVE_SCHEMA_PROBE',flush=True)
for path in [root/'data/ten-year-runners/2017-01.json.gz',root/'data/ten-year-runners/2020-07.json.gz',root/'data/ten-year-runners/2026-08.json.gz']:
 try:
  x=json.load(gzip.open(path,'rt',encoding='utf8'))
  def preview(y,d=0):
   if isinstance(y,dict):
    return {'type':'dict','keys':list(y.keys())[:40],'sample':{k:preview(v,d+1) for k,v in list(y.items())[:3]}} if d<3 else {'type':'dict','keys':list(y.keys())[:20]}
   if isinstance(y,list):return {'type':'array','size':len(y),'first':preview(y[0],d+1)} if d<4 and y else {'type':'array','size':len(y)}
   return str(y)[:90]
  print('MONTH',path.name,json.dumps(preview(x),ensure_ascii=False)[:4500],flush=True)
  print('MONTH_FIRST_RECORD',path.name,json.dumps(x[0],ensure_ascii=False)[:3200],flush=True)
 except Exception as e:print('MONTH_FAIL',path.name,type(e).__name__,str(e)[:300],flush=True)
parts=sorted((root/'src/v1/ten-year-history-data').glob('bin-*.ts'))
a=''.join(json.loads(p.read_text().strip()[len('export default '):-1]) for p in parts)
z=json.loads(gzip.decompress(base64.b64decode(a)))
print('EMBEDDED_ARCHIVE',list(z),len(z['races']),'FIRST',json.dumps(z['races'][0],ensure_ascii=False)[:1400],flush=True)
print('EMBEDDED_ARCHIVE_LAST',json.dumps(z['races'][-1],ensure_ascii=False)[:1400],flush=True)
