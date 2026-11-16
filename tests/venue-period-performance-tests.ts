import {strict as assert} from "node:assert";
import {NORMAL_HOME_SNAPSHOT} from "../src/normal-home-snapshot.js";
import {removeUnusedHomeSections} from "../src/v1/retired-public-features-ui.js";
import {addVenuePeriodExplorer,foldRoiDisplay,VENUE_PERIOD_UI_SCRIPT} from "../src/v1/venue-period-ui.js";
import {historicalCumulativeBaseline} from "../src/v1/cumulative-performance.js";
import {acceptedProductionRows,buildVenuePeriods,venuePeriodResponse,
  refreshVenuePeriodsIfDue,VENUE_PERIOD_STATE_KEY,VENUE_PERIOD_VERSION}
  from "../src/v1/venue-period-performance.js";

const original=historicalCumulativeBaseline();
const history=buildVenuePeriods([],[],"2026-08-09","2026-11-16T04:20:00Z",null);
assert.equal(history.version,VENUE_PERIOD_VERSION);
assert.equal(history.historicalRaces,14410);
assert.equal(history.productionRaces,0);
assert.equal(history.months.filter(x=>x.venue!=="全会場").reduce((n,x)=>n+x.races,0),14410);
assert.equal(history.months.filter(x=>x.venue==="全会場").reduce((n,x)=>n+x.stakeYen,0),28820000);
assert.equal(history.months.filter(x=>x.venue==="全会場").reduce((n,x)=>n+x.returnYen,0),124401700);
assert.equal(history.years.filter(x=>x.venue==="全会場").reduce((n,x)=>n+x.races,0),14410);
assert.equal(history.years.filter(x=>x.venue==="全会場").reduce((n,x)=>n+x.returnYen,0),124401700);
for(const reference of original.venues){
  const years=history.years.filter(x=>x.venue===reference.venue);
  assert.equal(years.reduce((n,x)=>n+x.races,0),reference.races,reference.venue+" race count");
  assert.equal(years.reduce((n,x)=>n+x.stakeYen,0),reference.stakeYen,reference.venue+" stake");
  assert.equal(years.reduce((n,x)=>n+x.returnYen,0),reference.returnYen,reference.venue+" return");
}
assert.ok(history.years.some(x=>x.period==="2016"));
assert.ok(history.years.some(x=>x.period==="2026"));
assert.ok(history.months.some(x=>x.period==="2026-08"));
const samples=[
  {raceDate:"2026-08-09",raceId:"historical",venue:"東京",rowCount:2,settledRows:2,stakeYen:2000,returnYen:50000},
  {raceDate:"2026-08-10",raceId:"new1",venue:"新潟",rowCount:2,settledRows:2,stakeYen:2000,returnYen:6500},
  {raceDate:"2026-08-11",raceId:"partial",venue:"東京",rowCount:2,settledRows:1,stakeYen:1000,returnYen:8000},
  {raceDate:"2026-11-15",raceId:"missing",venue:"東京",rowCount:1,settledRows:1,stakeYen:1000,returnYen:12000},
  {raceDate:"2026-11-16",raceId:"other",venue:"京都",rowCount:2,settledRows:2,stakeYen:2000,returnYen:0},
  {raceDate:"2026-11-16",raceId:"wrong-course",venue:"中京",rowCount:2,settledRows:2,stakeYen:5000,returnYen:9000}
];
const accepted=acceptedProductionRows(samples);
assert.equal(accepted.reduce((n,x)=>n+x[2],0),2);
assert.equal(accepted.reduce((n,x)=>n+x[3],0),4000);
assert.equal(accepted.reduce((n,x)=>n+x[4],0),6500);
const withLive=buildVenuePeriods([],accepted,"2026-11-15","2026-11-16T04:20:00Z",null);
assert.equal(withLive.productionRaces,2);
const canonicalNiigataAug=history.months.find(x=>x.venue==="新潟"&&x.period==="2026-08");
const liveNiigataAug=withLive.months.find(x=>x.venue==="新潟"&&x.period==="2026-08");
assert.ok(canonicalNiigataAug&&liveNiigataAug);
assert.equal(liveNiigataAug.races,canonicalNiigataAug.races+1);
assert.equal(liveNiigataAug.returnYen,canonicalNiigataAug.returnYen+6500);
const niigata2026=withLive.years.find(x=>x.venue==="新潟"&&x.period==="2026")!;
assert.ok(niigata2026);
assert.equal(niigata2026.stakeYen,history.years.find(x=>x.venue==="新潟"&&x.period==="2026")!.stakeYen+2000);
const overall2026=withLive.years.find(x=>x.venue==="全会場"&&x.period==="2026")!;
assert.ok(Math.abs(overall2026.roiPct-(overall2026.returnYen/overall2026.stakeYen*100))<1e-8);

const home=removeUnusedHomeSections(NORMAL_HOME_SNAPSHOT);
const enhanced=addVenuePeriodExplorer(home);
assert.ok(enhanced.includes('id="venue-period-roi"'));
assert.ok(enhanced.includes("会場別・年別／月別回収率"));
assert.ok(enhanced.includes("data-venue-period-mode="));
assert.ok(enhanced.includes("/api/public/venue-period-performance"));
assert.ok(enhanced.indexOf('id="venue-period-roi"')<enhanced.indexOf('class="daily-performance-wrap"'));
assert.ok(enhanced.includes('id="races"'),"do not delete canonical race selection");
assert.ok(enhanced.includes("会場別回収率"),"keep existing venue total");
assert.ok(!enhanced.includes('href="/win5"'));
assert.ok(!enhanced.includes('href="/adhoc"'));
assert.equal(enhanced,addVenuePeriodExplorer(enhanced),"do not inject duplicate panels or scripts");

const folded=foldRoiDisplay(enhanced);
assert.ok(folded.includes('<details class="roi-collapse" id="roi-fold">'),"single native accordion");
assert.ok(folded.includes('<summary aria-label="回収率を見る・閉じる">'),"accessible tap to expand");
assert.ok(!/<details\b[^>]*\bid="roi-fold"[^>]*\bopen\b/.test(folded),"initial state CLOSED");
const foldStart=folded.indexOf('<details class="roi-collapse" id="roi-fold">');
const foldEnd=folded.indexOf('</div></details><section class="daily-performance-wrap"',foldStart);
assert.ok(foldEnd>foldStart,"every ROI panel must close before the normal daily summary");
const closedBody=folded.slice(foldStart,foldEnd);
for(const snippet of ['累計回収率','class="metrics shared-roi"',
  '会場別回収率','class="venue-roi-rail shared-venue-roi"',
  'id="venue-period-roi"','会場別・年別／月別回収率']){
  assert.ok(closedBody.includes(snippet),"folded ROI is missing "+snippet);
}
assert.ok(folded.includes('id="races"'),"keep actual race list and date/venue controls");
assert.ok(folded.includes('class="daily-performance-wrap"'),"keep live daily summary");
assert.ok(folded.includes("本日の集計"),"keep daily performance");
assert.ok(folded.includes("日別回収率"),"keep daily history");
assert.ok(!folded.includes('href="/win5"')&&!folded.includes('href="/adhoc"'),"keep retired navigation absent");
assert.equal(folded,foldRoiDisplay(folded),"fold is idempotent");
assert.equal(foldRoiDisplay("<html><body><h1>他の画面</h1></body></html>"),
  "<html><body><h1>他の画面</h1></body></html>",
  "never wrap race detail or other pages");
assert.ok(VENUE_PERIOD_UI_SCRIPT.includes('roiFold.addEventListener'),
  "expand gesture must trigger fresh live-month/year fetch");
assert.ok(VENUE_PERIOD_UI_SCRIPT.includes('if(loading||document.hidden||!'),
  "do not query live monthly/yearly ROI when panel is closed");


const saved={
  version:VENUE_PERIOD_VERSION,
  closedThroughDate:"2026-11-14",updatedAt:"2026-11-15T10:05:00Z",
  months:[["東京","2026-11",1,2000,6000]]
};
const sqls:string[]=[];
const db={
  prepare:(sql:string)=>({
    bind:(...args:unknown[])=>({
      first:async()=>{
        sqls.push("first "+sql);
        assert.equal(args[0],VENUE_PERIOD_STATE_KEY);
        return {value:JSON.stringify(saved)};
      },
      all:async()=>{
        sqls.push("all "+sql);
        if(String(args[0])==="2026-11-14"){
          return {results:[
            {raceDate:"2026-11-15",raceId:"correct",venue:"東京",rowCount:2,settledRows:2,stakeYen:2000,returnYen:8000},
            {raceDate:"2026-11-16",raceId:"pending",venue:"東京",rowCount:2,settledRows:1,stakeYen:1000,returnYen:9000}
          ]};
        }
        assert.equal(args[0],"2026-08-09");
        return {results:[
          {raceDate:"2026-11-15",raceId:"correct",venue:"東京",rowCount:2,settledRows:2,stakeYen:2000,returnYen:8000},
          {raceDate:"2026-11-16",raceId:"pending",venue:"東京",rowCount:2,settledRows:1,stakeYen:1000,returnYen:9000}
        ]};
      },
      run:async()=>{
        sqls.push("run "+sql);
        return {success:true};
      }
    })
  })
} as unknown as D1Database;
const response=await venuePeriodResponse(db,new Date("2026-11-16T04:20:00Z"));
assert.equal(response.status,200);
const json=await response.json() as ReturnType<typeof buildVenuePeriods>;
assert.equal(json.productionRaces,2);
assert.equal(json.asOfDate,"2026-11-16");
assert.equal(json.months.find(x=>x.venue==="東京"&&x.period==="2026-11")!.stakeYen,4000);
assert.equal(json.months.find(x=>x.venue==="東京"&&x.period==="2026-11")!.returnYen,14000);
assert.ok(sqls.some(x=>x.includes("b.source_prediction_id=-2")&&x.includes("b.course='ライト'")));
assert.ok(sqls.every(x=>!x.startsWith("run ")),"public GET must never mutate D1");
const offWindow=await refreshVenuePeriodsIfDue({DB:db} as never,new Date("2026-11-16T04:20:00Z"));
assert.equal(offWindow.status,"outside_window");
assert.ok(sqls.every(x=>!x.startsWith("run ")),"5-minute maintenance cron is read free outside nightly refresh");
const daily=await refreshVenuePeriodsIfDue({DB:db} as never,new Date("2026-11-16T10:05:00Z"));
assert.equal(daily.status,"updated");
assert.equal(daily.closedThroughDate,"2026-11-15");
assert.ok(sqls.some(x=>x.startsWith("run ")),"nightly refresh must write a single aggregate");
console.log("VENUE_MONTH_YEAR_ROI_ALL_10_VENUES_14410_ARCHIVE_LIVE_D1_AND_HOMEPAGE_OK");
