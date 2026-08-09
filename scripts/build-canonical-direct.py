import base64, gzip, json, pathlib, re

ROOT=pathlib.Path(__file__).resolve().parents[1]
V1=ROOT/'src'/'v1'
OUT=V1/'canonical-history-direct.ts'
VENUE_SLUG={'札幌':'sapporo','函館':'hakodate','福島':'fukushima','新潟':'niigata','東京':'tokyo','中山':'nakayama','中京':'chukyo','京都':'kyoto','阪神':'hanshin','小倉':'kokura'}

def selected(year:int):
    text=(V1/f'frozen-selected-{year}.ts').read_text(encoding='utf-8')
    body=text.split('=',1)[1].rsplit(';',1)[0]
    return json.loads(body)

def bin_text(i:int):
    text=(V1/'canonical-history-data'/f'bin-{i:02d}.ts').read_text(encoding='utf-8')
    m=re.search(r'export default\s+(["\'])(.*?)\1\s*;?\s*$',text,re.S)
    if not m: raise RuntimeError(f'BAD_BIN:{i}')
    return bytes(m.group(2),'utf-8').decode('unicode_escape')

def read_varint(data:bytes,pos:int):
    value=0; shift=0
    while pos<len(data):
        b=data[pos]; pos+=1; value|=(b&127)<<shift
        if b<128: return value,pos
        shift+=7
        if shift>28: raise RuntimeError('VARINT_TOO_LARGE')
    raise RuntimeError('TRUNCATED')

ids=[]
for year in (2024,2025,2026):
    for key,value in selected(year).items():
        date,venue=key.split('|',1)
        if date>'2026-08-02': continue
        slug=VENUE_SLUG[venue]
        for race_no in value.split('.'):
            ids.append(f'{date}-{slug}-{int(race_no):02d}')
if len(ids)!=3210: raise RuntimeError(f'RACE_COUNT:{len(ids)}')

encoded=''.join(bin_text(i) for i in range(4))
data=gzip.decompress(base64.b64decode(encoded))
pos=0
count,pos=read_varint(data,pos)
if count!=len(ids): raise RuntimeError(f'ARCHIVE_COUNT:{count}/{len(ids)}')
out={}; ticket_count=0
for race_id in ids:
    n,pos=read_varint(data,pos); rows=[]
    for _ in range(n):
        bet,pos=read_varint(data,pos); combo,pos=read_varint(data,pos); obin,pos=read_varint(data,pos)
        rows.append([bet,combo,obin,0])
    winners,pos=read_varint(data,pos)
    for _ in range(winners):
        idx,pos=read_varint(data,pos); payout,pos=read_varint(data,pos); rows[idx][3]=payout
    ticket_count+=n; out[race_id]=rows
if pos!=len(data) or ticket_count!=17735: raise RuntimeError(f'INTEGRITY:{pos}/{len(data)}/{ticket_count}')

payload=json.dumps(out,ensure_ascii=False,separators=(',',':'))
OUT.write_text('export const DIRECT_CANONICAL_HISTORY:Record<string,number[][]>='+payload+';\n',encoding='utf-8')
print(json.dumps({'races':len(out),'tickets':ticket_count,'bytes':OUT.stat().st_size},ensure_ascii=False))
