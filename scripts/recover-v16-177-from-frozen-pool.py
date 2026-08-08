import base64,json,zlib
from pathlib import Path
p=json.loads(Path('config/v16-uniform-rule-model.json').read_text())
raw=json.loads(zlib.decompress(base64.b64decode(p['rulePayload'])).decode())
r=[]
for cols,vals,q in raw['r']:
    r.append({'cols':cols,'vals':vals,'quality':float(q)})
r.sort(key=lambda x:-x['quality'])
qs=[x['quality'] for x in r]
# Report exact top-177 boundary and natural quality cut counts.
thresholds=sorted(set(qs),reverse=True)
natural=[]
for t in thresholds:
    c=sum(q>=t for q in qs)
    if 150<=c<=220:
        natural.append({'threshold':t,'count':c})
out={'count':len(r),'top177MinQuality':qs[176],'nextQuality':qs[177],
     'tiesAtBoundary':sum(abs(q-qs[176])<1e-15 for q in qs),
     'naturalCuts150to220':natural[:100],
     'top177':r[:177]}
Path('artifacts').mkdir(exist_ok=True)
Path('artifacts/v16-177-recovery-probe.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in out.items() if k!='top177'},ensure_ascii=False))
