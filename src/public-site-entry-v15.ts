import publicSite from "./public-site-entry-v14.js";
import { TEN_YEAR_MONTHLY, TEN_YEAR_PUBLIC_LIGHT_RETURN_YEN, TEN_YEAR_PUBLIC_RACES, TEN_YEAR_VENUES } from "./v1/ten-year-public-summary.js";
import type { Env } from "./v1/types.js";

const CUTOFF="2026-08-09";
const HOME_COURSE="ライト";
const HOME_BUDGET=2000;
type CourseRow={course:string;settledRaces:number;stakeYen:number;returnYen:number};
type MonthlyRow=CourseRow&{month:string};
type VenueRow=CourseRow&{venue:string};

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
  const add=live.find(x=>x.course===HOME_COURSE);
  const races=TEN_YEAR_PUBLIC_RACES+(add?.settledRaces??0);
  const stake=TEN_YEAR_PUBLIC_RACES*HOME_BUDGET+(add?.stakeYen??0);
  const ret=TEN_YEAR_PUBLIC_LIGHT_RETURN_YEN+(add?.returnYen??0);
  const monthlyMap=new Map<string,{races:number;stake:number;ret:number}>();
  for(const row of TEN_YEAR_MONTHLY)monthlyMap.set(row.month,{races:row.races,stake:row.races*HOME_BUDGET,ret:row.returnLightYen});
  for(const x of monthlyLive.filter(x=>x.course===HOME_COURSE)){
    const prev=monthlyMap.get(x.month)??{races:0,stake:0,ret:0};
    monthlyMap.set(x.month,{races:prev.races+x.settledRaces,stake:prev.stake+x.stakeYen,ret:prev.ret+x.returnYen});
  }
  const months=[...monthlyMap.keys()].sort().reverse();
  const monthRows=months.map(month=>{const x=monthlyMap.get(month)!;return `<div class="monthly-row"><b>${month.replace("-","/")}</b><span>${x.races.toLocaleString("ja-JP")}R</span><strong class="${roi(x.stake,x.ret)>=100?"plus":"minus"}">${roi(x.stake,x.ret).toFixed(1)}%</strong></div>`;}).join("");
  return `<section class="metrics shared-roi"><details class="card metric"><summary><b>全体</b><strong>${roi(stake,ret).toFixed(1)}%</strong><small>${races.toLocaleString("ja-JP")}R</small></summary><div class="monthly">${monthRows}</div></details></section>`;
}

function venueHtml(live:VenueRow[]):string{
  const liveMap=new Map(live.filter(x=>x.course===HOME_COURSE).map(x=>[x.venue,x]));
  const totalLiveRaces=[...liveMap.values()].reduce((s,x)=>s+x.settledRaces,0);
  const cards=TEN_YEAR_VENUES.map(v=>{
    const add=liveMap.get(v.venue);const races=v.races+(add?.settledRaces??0);const stake=v.races*HOME_BUDGET+(add?.stakeYen??0);const ret=v.returnLightYen+(add?.returnYen??0);const value=roi(stake,ret);
    return `<article class="venue-roi-card"><div class="venue-roi-head"><b>${v.venue}</b><span>${races.toLocaleString("ja-JP")}R</span></div><strong class="venue-roi-value ${value>=100?"venue-roi-plus":"venue-roi-minus"}">${value.toFixed(1)}%</strong></article>`;
  }).join("");
  return `<div class="section-title venue-roi-title"><h2>会場別回収率</h2><span class="muted">全期間・${(TEN_YEAR_PUBLIC_RACES+totalLiveRaces).toLocaleString("ja-JP")}R</span></div><div class="venue-roi-rail shared-venue-roi">${cards}</div>`;
}

function homeStyle():string{
  return `<style>
    .shared-roi{grid-template-columns:minmax(0,1fr)!important}.shared-roi .metric{max-width:none}.shared-roi .metric summary{display:grid;grid-template-columns:1fr auto;align-items:end;gap:4px 16px}.shared-roi .metric summary>b{grid-column:1}.shared-roi .metric summary>strong{grid-column:1;font-size:40px}.shared-roi .metric summary>small{grid-column:2;grid-row:1 / span 2;align-self:center;font-size:13px}.shared-venue-roi .venue-roi-card{min-height:112px}.shared-venue-roi .venue-roi-value{display:block;margin-top:14px;font-size:27px;font-weight:900}.shared-venue-roi .venue-roi-head{align-items:center}
    .today-result .today-result-row:nth-of-type(n+3){display:none}.today-result .today-result-row>div:first-child>b{display:none}.today-result .today-result-money>span{display:none}.today-result .today-result-row>div:first-child{display:block}.today-result .today-result-row>div:first-child>span{font-size:12px}.today-result .today-result-money strong{font-size:20px}
    @media(max-width:760px){.shared-roi .metric summary>strong{font-size:36px}.shared-venue-roi .venue-roi-card{min-height:104px}.shared-venue-roi .venue-roi-value{font-size:25px}}
  </style>`;
}

function replaceVenueRoi(html:string,replacement:string):string{
  const start=html.indexOf('<div class="section-title venue-roi-title">');
  if(start<0)return html;
  const candidates=[
    html.indexOf('<section class="today-result"',start),
    html.indexOf('<div class="section-title"><h2 id="selected-date">',start)
  ].filter((value)=>value>start);
  if(!candidates.length)return html;
  const end=Math.min(...candidates);
  return html.slice(0,start)+replacement+html.slice(end);
}

async function canonicalHome(db:D1Database,html:string):Promise<string>{
  const [courses,months,venues]=await Promise.all([liveCourseRows(db),liveMonthlyRows(db),liveVenueRows(db)]);
  let out=html.replace(/<section class="metrics">[\s\S]*?<\/section>/,metricHtml(courses,months));
  out=replaceVenueRoi(out,venueHtml(venues));
  out=out.replace("</head>",`${homeStyle()}</head>`);
  return out;
}

export default {
  async fetch(request:Request,env:Env,ctx:ExecutionContext):Promise<Response>{
    if(!publicSite.fetch)return new Response("NOT_FOUND",{status:404});
    const response=await publicSite.fetch(request,env,ctx);
    if(new URL(request.url).pathname!=="/"||!response.ok||!response.headers.get("content-type")?.includes("text/html"))return response;
    try{const headers=new Headers(response.headers);headers.delete("content-length");headers.set("cache-control","no-store, max-age=0");headers.set("x-race-ui-version","ten-year-completed-v15-shared-roi");return new Response(await canonicalHome(env.DB,await response.text()),{status:response.status,headers});}catch{return response;}
  },
  async scheduled(controller:ScheduledController,env:Env,ctx:ExecutionContext):Promise<void>{if(publicSite.scheduled)await publicSite.scheduled(controller,env,ctx);}
} satisfies ExportedHandler<Env>;
