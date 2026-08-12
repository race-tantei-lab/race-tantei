import publicSite from "./public-site-entry-v14.js";
import { TEN_YEAR_MONTHLY, TEN_YEAR_PUBLIC_LIGHT_RETURN_YEN, TEN_YEAR_PUBLIC_RACES, TEN_YEAR_VENUES } from "./v1/ten-year-public-summary.js";
import type { Env } from "./v1/types.js";

const CUTOFF="2026-08-09";
const COURSES=[
  {course:"ライト",budget:2000,scale:1},
  {course:"スタンダード",budget:5000,scale:2.5},
  {course:"プレミアム",budget:10000,scale:5}
] as const;
type Course=typeof COURSES[number]["course"];
type CourseRow={course:string;settledRaces:number;stakeYen:number;returnYen:number};
type MonthlyRow=CourseRow&{month:string};
type VenueRow=CourseRow&{venue:string};

function yen(value:number):string{return `¥${Math.round(value).toLocaleString("ja-JP")}`;}
function roi(stake:number,ret:number):number{return stake>0?ret/stake*100:0;}

async function liveCourseRows(db:D1Database):Promise<CourseRow[]>{
  try{return (await db.prepare(`
    SELECT b.course AS course,COUNT(DISTINCT b.race_id) AS settledRaces,
           COALESCE(SUM(b.stake_yen),0) AS stakeYen,COALESCE(SUM(b.return_yen),0) AS returnYen
    FROM rt_public_bets b JOIN rt_races r ON r.race_id=b.race_id
    WHERE r.race_date>? AND b.settlement_status='settled'
    GROUP BY b.course
  `).bind(CUTOFF).all<CourseRow>()).results.map(x=>({...x,settledRaces:Number(x.settledRaces),stakeYen:Number(x.stakeYen),returnYen:Number(x.returnYen)}));}catch{return [];}
}
async function liveMonthlyRows(db:D1Database):Promise<MonthlyRow[]>{
  try{return (await db.prepare(`
    SELECT substr(r.race_date,1,7) AS month,b.course AS course,COUNT(DISTINCT b.race_id) AS settledRaces,
           COALESCE(SUM(b.stake_yen),0) AS stakeYen,COALESCE(SUM(b.return_yen),0) AS returnYen
    FROM rt_public_bets b JOIN rt_races r ON r.race_id=b.race_id
    WHERE r.race_date>? AND b.settlement_status='settled'
    GROUP BY substr(r.race_date,1,7),b.course
  `).bind(CUTOFF).all<MonthlyRow>()).results.map(x=>({...x,settledRaces:Number(x.settledRaces),stakeYen:Number(x.stakeYen),returnYen:Number(x.returnYen)}));}catch{return [];}
}
async function liveVenueRows(db:D1Database):Promise<VenueRow[]>{
  try{return (await db.prepare(`
    SELECT r.venue AS venue,b.course AS course,COUNT(DISTINCT b.race_id) AS settledRaces,
           COALESCE(SUM(b.stake_yen),0) AS stakeYen,COALESCE(SUM(b.return_yen),0) AS returnYen
    FROM rt_public_bets b JOIN rt_races r ON r.race_id=b.race_id
    WHERE r.race_date>? AND b.settlement_status='settled'
    GROUP BY r.venue,b.course
  `).bind(CUTOFF).all<VenueRow>()).results.map(x=>({...x,settledRaces:Number(x.settledRaces),stakeYen:Number(x.stakeYen),returnYen:Number(x.returnYen)}));}catch{return [];}
}

function metricHtml(live:CourseRow[],monthlyLive:MonthlyRow[]):string{
  const liveBy=new Map(live.map(x=>[x.course,x]));
  const monthlyMap=new Map<string,{races:number;stake:number;ret:number}>();
  for(const row of TEN_YEAR_MONTHLY){for(const c of COURSES){monthlyMap.set(`${row.month}|${c.course}`,{races:row.races,stake:row.races*c.budget,ret:Math.round(row.returnLightYen*c.scale)});}}
  for(const x of monthlyLive){const key=`${x.month}|${x.course}`;const prev=monthlyMap.get(key)??{races:0,stake:0,ret:0};monthlyMap.set(key,{races:prev.races+x.settledRaces,stake:prev.stake+x.stakeYen,ret:prev.ret+x.returnYen});}
  const months=[...new Set([...TEN_YEAR_MONTHLY.map(x=>x.month),...monthlyLive.map(x=>x.month)])].sort().reverse();
  return `<section class="metrics">${COURSES.map(c=>{
    const add=liveBy.get(c.course);const races=TEN_YEAR_PUBLIC_RACES+(add?.settledRaces??0);const stake=TEN_YEAR_PUBLIC_RACES*c.budget+(add?.stakeYen??0);const ret=Math.round(TEN_YEAR_PUBLIC_LIGHT_RETURN_YEN*c.scale)+(add?.returnYen??0);
    const monthRows=months.map(month=>{const x=monthlyMap.get(`${month}|${c.course}`);if(!x)return "";return `<div class="monthly-row"><b>${month.replace("-","/")}</b><span>${x.races}R　${yen(x.stake)} → ${yen(x.ret)}</span><strong class="${roi(x.stake,x.ret)>=100?"plus":"minus"}">${roi(x.stake,x.ret).toFixed(1)}%</strong></div>`;}).join("");
    return `<details class="card metric"><summary><b>${c.course}</b><strong>${roi(stake,ret).toFixed(1)}%</strong><small>${races}R　購入 ${yen(stake)}　払戻 ${yen(ret)}</small></summary><div class="monthly">${monthRows}</div></details>`;
  }).join("")}</section>`;
}

function venueHtml(live:VenueRow[]):string{
  const liveMap=new Map(live.map(x=>[`${x.venue}|${x.course}`,x]));
  const totalLiveRaces=Math.max(0,...COURSES.map(c=>live.filter(x=>x.course===c.course).reduce((s,x)=>s+x.settledRaces,0)));
  const cards=TEN_YEAR_VENUES.map(v=>{
    const rows=COURSES.map(c=>{const add=liveMap.get(`${v.venue}|${c.course}`);const races=v.races+(add?.settledRaces??0);const stake=v.races*c.budget+(add?.stakeYen??0);const ret=Math.round(v.returnLightYen*c.scale)+(add?.returnYen??0);return {course:c.course,races,value:roi(stake,ret)};});
    return `<article class="venue-roi-card"><div class="venue-roi-head"><b>${v.venue}</b><span>${rows[0].races}R</span></div>${rows.map(x=>`<div class="venue-roi-row"><span>${x.course}</span><strong class="${x.value>=100?"venue-roi-plus":"venue-roi-minus"}">${x.value.toFixed(1)}%</strong></div>`).join("")}</article>`;
  }).join("");
  return `<div class="section-title venue-roi-title"><h2>会場別回収率</h2><span class="muted">全期間・${(TEN_YEAR_PUBLIC_RACES+totalLiveRaces).toLocaleString("ja-JP")}R</span></div><div class="venue-roi-rail">${cards}</div>`;
}

async function canonicalHome(db:D1Database,html:string):Promise<string>{
  const [courses,months,venues]=await Promise.all([liveCourseRows(db),liveMonthlyRows(db),liveVenueRows(db)]);
  let out=html.replace(/<section class="metrics">[\s\S]*?<\/section>/,metricHtml(courses,months));
  out=out.replace(/<div class="section-title venue-roi-title">[\s\S]*?<\/div><div class="venue-roi-rail">[\s\S]*?<\/div>(?=<div class="section-title"><h2 id="selected-date">)/,venueHtml(venues));
  return out;
}

export default {
  async fetch(request:Request,env:Env,ctx:ExecutionContext):Promise<Response>{
    if(!publicSite.fetch)return new Response("NOT_FOUND",{status:404});
    const response=await publicSite.fetch(request,env,ctx);
    if(new URL(request.url).pathname!=="/"||!response.ok||!response.headers.get("content-type")?.includes("text/html"))return response;
    try{const headers=new Headers(response.headers);headers.delete("content-length");headers.set("cache-control","no-store, max-age=0");headers.set("x-race-ui-version","ten-year-completed-v15");return new Response(await canonicalHome(env.DB,await response.text()),{status:response.status,headers});}catch{return response;}
  },
  async scheduled(controller:ScheduledController,env:Env,ctx:ExecutionContext):Promise<void>{if(publicSite.scheduled)await publicSite.scheduled(controller,env,ctx);}
} satisfies ExportedHandler<Env>;
