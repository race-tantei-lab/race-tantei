#!/usr/bin/env python3
"""Build immutable JRA venue/month benchmark from the exact 10-year archive.

Never uses the non-operational 716% research cash allocator. The source is
the 14,410 selected 2-ticket canonical original-model historical races.
Runs during CI/build; never queries D1 or overwrites past betting records.
"""
import base64,collections,gzip,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"src/v1/ten-year-history-data"
OUT=ROOT/"src/v1/venue-period-history.json"
EXPECTED={
    "札幌":(670,1340000,5330600),
    "函館":(600,1200000,5272100),
    "福島":(960,1920000,10264200),
    "新潟":(1360,2720000,12600700),
    "東京":(2230,4460000,17897900),
    "中山":(2085,4170000,16402800),
    "中京":(1515,3030000,11882300),
    "京都":(1705,3410000,13982100),
    "阪神":(2115,4230000,16787400),
    "小倉":(1170,2340000,13981600),
}
def build():
    chunks=sorted(DATA.glob("bin-*.ts"))
    assert len(chunks)==9,"Expected all nine historical archives"
    encoded=""
    for chunk in chunks:
        src=chunk.read_text(encoding="utf8").strip()
        assert src.startswith("export default "),chunk
        encoded+=json.loads(src[len("export default "):].rstrip(";"))
    raw=json.loads(gzip.decompress(base64.b64decode(encoded)))
    assert (raw["start"],raw["end"],len(raw["races"]))==("2016-08-10","2026-08-09",34566)
    grouped=collections.defaultdict(lambda:[0,0,0])
    venues=collections.defaultdict(lambda:[0,0,0])
    total=[0,0,0]
    for item in raw["races"]:
        tickets=item[8]
        if tickets is None:
            continue
        assert len(tickets)==2 and tickets[0][0]!=tickets[1][0]
        date=str(item[1]);venue=str(item[2]);month=date[:7]
        assert "2016-08-10"<=date<="2026-08-09" and venue in EXPECTED
        stake=2000
        paid=sum(int(t[3]) for t in tickets)
        assert paid>=0
        for slot in (grouped[(venue,month)],venues[venue],total):
            slot[0]+=1;slot[1]+=stake;slot[2]+=paid
    assert total==[14410,28820000,124401700],total
    assert {venue:tuple(v) for venue,v in venues.items()}==EXPECTED,"Venue totals differ from cumulative production benchmark"
    rows=[[venue,month,*value] for (venue,month),value in sorted(grouped.items())]
    assert sum(row[2] for row in rows)==14410
    assert sum(row[3] for row in rows)==28820000
    assert sum(row[4] for row in rows)==124401700
    return json.dumps({
        "schema":"jra-venue-month-history-canonical-v1",
        "historicalThrough":"2026-08-09",
        "liveFrom":"2026-08-10",
        "total":{"races":total[0],"stakeYen":total[1],"returnYen":total[2]},
        "venues":list(EXPECTED),
        "months":rows,
    },ensure_ascii=False,separators=(",",":"),sort_keys=True)+"\n"
def main():
    value=build()
    if "--check" in sys.argv:
        assert OUT.is_file() and OUT.read_text(encoding="utf8")==value,"VENUE_MONTH_ARCHIVE_MISSING_OR_CHANGED"
    else:
        OUT.write_text(value,encoding="utf8")
    print("CANONICAL_VENUE_MONTH_HISTORY_FINANCIAL_PARITY_OK",len(value.encode("utf8")))
if __name__=="__main__":
    main()
