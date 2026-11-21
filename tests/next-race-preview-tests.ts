import {strict as assert} from "node:assert";
import {NORMAL_HOME_SNAPSHOT} from "../src/normal-home-snapshot.js";
import {removeUnusedHomeSections} from "../src/v1/retired-public-features-ui.js";
import {addVenuePeriodExplorer,foldRoiDisplay} from "../src/v1/venue-period-ui.js";
import {addNextRacePreview,nextSelectedRace,nextRaceStartMs,jstDay,NEXT_RACE_SCRIPT}
  from "../src/v1/next-race-preview.js";
import type {NextRaceItem} from "../src/v1/next-race-preview.js";

const now=Date.parse("2026-11-21T03:15:00Z"); // 12:15 JST
assert.equal(jstDay(now),"2026-11-21");
const race=(id:string,utc:string,code:string,venue:string,extra:Partial<NextRaceItem>={}):NextRaceItem=>({
  raceId:id,raceDate:"2026-11-21",raceName:"試験レース",
  venue,raceNo:6,startTimeUtc:utc,startTimeJst:null,
  status:"scheduled",publicState:{code,label:"買い目対象"},...extra
});
const rows=[
  race("old","2026-11-21T03:10:00Z","buy","東京"), // already started
  race("unselected","2026-11-21T03:16:00Z","skip","京都"),
  race("nextKyoto","2026-11-21T03:25:00Z","target","京都",{
    startTimeJst:"12:25",raceNo:7,raceName:"対象7R"
  }),
  race("nextTokyo","2026-11-21T03:35:00Z","buy","東京"),
  race("cancelled","2026-11-21T03:18:00Z","target","阪神",{status:"cancelled"}),
  race("no-final","2026-11-21T03:19:00Z","pending","京都",{publicState:{code:"pending",label:"判定中"}}),
  race("processing","2026-11-21T03:22:00Z","pending","東京",{publicState:{code:"pending",label:"最終計算中（確定前）"}}),
  race("overdue","2026-11-21T03:20:00Z","overdue","京都"),
  race("tomorrow","2026-11-22T02:00:00Z","buy","東京",{raceDate:"2026-11-22"})
];
assert.equal(nextSelectedRace(rows,now)?.raceId,"processing");
assert.equal(nextSelectedRace(rows,Date.parse("2026-11-21T03:23:00Z"))?.raceId,"nextKyoto");
assert.equal(nextSelectedRace(rows,Date.parse("2026-11-21T03:26:00Z"))?.raceId,"nextTokyo");
assert.equal(nextSelectedRace(rows,Date.parse("2026-11-21T03:40:00Z")),null);
assert.equal(nextSelectedRace(rows,Date.parse("2026-11-22T03:40:00Z")),null);
assert.equal(nextSelectedRace(rows.filter(x=>x.publicState?.code==="skip"),now),null);
const fallback=race("fallback","", "buy","阪神",{startTimeUtc:null,startTimeJst:"12:40"});
assert.equal(nextRaceStartMs(fallback),Date.parse("2026-11-21T03:40:00Z"));
assert.equal(nextSelectedRace([fallback],now)?.raceId,"fallback");
const tie=[race("zzz","2026-11-21T03:30:00Z","buy","京都"),race("aaa","2026-11-21T03:30:00Z","target","東京")];
assert.equal(nextSelectedRace(tie,now)?.raceId,"aaa");

const home=foldRoiDisplay(addVenuePeriodExplorer(removeUnusedHomeSections(NORMAL_HOME_SNAPSHOT)));
const preview=addNextRacePreview(home);
assert.ok(preview.includes('<section class="next-target-race" id="next-target-race" hidden'));
assert.ok(preview.indexOf('id="next-target-race"')<preview.indexOf('id="roi-fold"'),
  "next race preview should appear above folded ROI");
assert.ok(preview.indexOf('id="next-target-race"')<preview.indexOf('id="races"'));
assert.ok(preview.includes("次の対象レース"));
assert.equal(preview,addNextRacePreview(preview),"no duplicate previews or listeners");
assert.ok(preview.includes('id="races"')&&preview.includes('id="venue-period-roi"'),"keep canonical race/ROI views");
assert.ok(preview.includes("本日の集計"),"keep today stats");
assert.ok(!preview.includes('href="/win5"')&&!preview.includes('href="/adhoc"'));
const before=home.match(/const dayRows=Array\.isArray\(data\.races\)\?data\.races:\[\];/g)||[];
const after=preview.match(/const dayRows=Array\.isArray\(data\.races\)\?data\.races:\[\];/g)||[];
assert.equal(before.length,1);
assert.equal(after.length,1);
assert.ok(preview.includes('document.dispatchEvent(new CustomEvent("rt:day-loaded",{detail:data}));const dayRows='),
  "reuse previously fetched public-day data after request validation");
assert.equal(preview.match(/fetch\("\/api\/public\/day/g)?.length??0,home.match(/fetch\("\/api\/public\/day/g)?.length??0,
  "do not add a network call");
assert.ok(!NEXT_RACE_SCRIPT.includes("fetch("),"preview must not issue additional API requests");
assert.ok(NEXT_RACE_SCRIPT.includes('document.addEventListener("rt:day-loaded"'));
assert.ok(NEXT_RACE_SCRIPT.includes("status!=="));
assert.ok(NEXT_RACE_SCRIPT.includes("r.publicState"));
assert.equal(addNextRacePreview("<html><body>Other detail</body></html>"),
  "<html><body>Other detail</body></html>");
console.log("NEXT_SELECTED_RACE_NO_EXTRA_D1_REQUESTS_AND_TOP_COMPACT_UI_OK");
