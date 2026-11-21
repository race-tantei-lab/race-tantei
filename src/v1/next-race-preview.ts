/**
 * "Next selected race" preview reuses the existing home /api/public/day
 * response. NO extra D1 reads, NO new requests, NO model calculations, and
 * NO changes to canonical 15-minute locks.
 */
export type NextRaceItem={
  raceId:string;raceDate:string;venue:string;raceNo:number;
  raceName:string|null;startTimeJst:string|null;startTimeUtc:string|null;
  status?:string|null;publicState?:{code:string;label:string}|null;
};
export function jstDay(atMs:number):string{
  return new Date(atMs+9*3600000).toISOString().slice(0,10);
}
export function nextRaceStartMs(r:NextRaceItem):number{
  const fromUtc=Date.parse(String(r.startTimeUtc??""));
  if(Number.isFinite(fromUtc))return fromUtc;
  const match=String(r.startTimeJst??"").match(/^(\d{1,2}):(\d{2})$/);
  if(!match)return NaN;
  return Date.parse(r.raceDate+"T"+match[1]!.padStart(2,"0")+":"+match[2]+":00+09:00");
}
export function nextSelectedRace(
  rows:readonly NextRaceItem[],nowMs:number
):NextRaceItem|null{
  const today=jstDay(nowMs);
  let chosen:NextRaceItem|null=null,earliest=Infinity;
  for(const r of rows){
    if(r.raceDate!==today||!r.raceId)continue;
    const state=r.publicState;
    const stateOk=state?.code==="buy"||state?.code==="target"||
      (state?.code==="pending"&&String(state.label??"").includes("最終計算中"));
    if(!stateOk||["cancelled","canceled","postponed"].includes(String(r.status??"").toLowerCase()))continue;
    const start=nextRaceStartMs(r);
    if(!Number.isFinite(start)||start<=nowMs)continue;
    if(start<earliest||(start===earliest&&r.raceId<(chosen?.raceId??"~"))){
      chosen=r;earliest=start;
    }
  }
  return chosen;
}
export const NEXT_RACE_CSS = "<style>"+
 ".next-target-race{border:1px solid var(--green,#51d0a5);background:linear-gradient(100deg,#133a33,#122534);border-radius:15px;margin:10px 0 14px;overflow:hidden}"+
 ".next-target-race[hidden]{display:none}"+
 ".next-target-race>a{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 15px;text-decoration:none;color:var(--text,#f2f5f8)}"+
 ".next-target-race>a:focus-visible{outline:2px solid var(--green,#51d0a5);outline-offset:-3px}"+
 ".next-target-label{display:block;font-size:11px;color:var(--green,#51d0a5);font-weight:800;margin-bottom:3px}"+
 ".next-target-title{font-size:15px;font-weight:850;display:block}"+
 ".next-target-info{display:block;font-size:11px;color:var(--muted,#9baec4);margin-top:3px}"+
 ".next-target-countdown{font-weight:900;white-space:nowrap;color:var(--green,#51d0a5);font-variant-numeric:tabular-nums;font-size:14px}"+
 "</style>";
export const NEXT_RACE_HTML=
 '<section class="next-target-race" id="next-target-race" hidden aria-label="次の対象レース">'+
 '<a id="next-target-race-link"><span>'+
 '<span class="next-target-label">次の対象レース</span>'+
 '<span class="next-target-title"><span id="next-target-race-venue"></span>　<span id="next-target-race-name"></span></span>'+
 '<span class="next-target-info" id="next-target-race-info"></span>'+
 '</span><span class="next-target-countdown" id="next-target-race-countdown"></span></a></section>';
export const NEXT_RACE_SCRIPT="<script>(function(){\n  \"use strict\";\n  var section=document.getElementById(\"next-target-race\");\n  var link=document.getElementById(\"next-target-race-link\");\n  if(!section||!link)return;\n  var venue=document.getElementById(\"next-target-race-venue\");\n  var name=document.getElementById(\"next-target-race-name\");\n  var info=document.getElementById(\"next-target-race-info\");\n  var countdown=document.getElementById(\"next-target-race-countdown\");\n  var cached=[];\n  function todayJst(now){\n    return new Date(now+9*3600000).toISOString().slice(0,10);\n  }\n  function startMs(r){\n    var utc=Date.parse(String(r.startTimeUtc||\"\"));\n    if(Number.isFinite(utc))return utc;\n    var m=String(r.startTimeJst||\"\").match(/^(\\d{1,2}):(\\d{2})$/);\n    if(!m)return NaN;\n    return Date.parse(String(r.raceDate)+\"T\"+m[1].padStart(2,\"0\")+\":\"+m[2]+\":00+09:00\");\n  }\n  function eligible(r,now){\n    var state=r&&r.publicState||{};\n    var valid=state.code===\"buy\"||state.code===\"target\"||\n      (state.code===\"pending\"&&String(state.label||\"\").indexOf(\"最終計算中\")>=0);\n    var status=String(r&&r.status||\"\").toLowerCase();\n    var when=startMs(r);\n    return valid && status!==\"cancelled\"&&status!==\"canceled\"&&status!==\"postponed\"&&\n      r.raceDate===todayJst(now)&&Number.isFinite(when)&&when>now;\n  }\n  function render(){\n    var now=Date.now();\n    var sorted=cached.filter(function(r){return eligible(r,now);}).sort(function(a,b){\n      return startMs(a)-startMs(b)||String(a.raceId).localeCompare(String(b.raceId));\n    });\n    var r=sorted[0];\n    if(!r){section.hidden=true;link.removeAttribute(\"href\");return;}\n    link.href=\"/races/\"+encodeURIComponent(String(r.raceId));\n    venue.textContent=String(r.venue||\"\")+\" \"+Number(r.raceNo)+\"R\";\n    name.textContent=String(r.raceName||\"\")+\"\";\n    var state=r.publicState||{};\n    var time=String(r.startTimeJst||\"\");\n    info.textContent=(time?time+\" 発走 • \":\"\")+\n      (state.code===\"buy\"?\"買い目確定\":state.code===\"target\"?\"買い目対象・確定前\":\"最終計算中\");\n    var minutes=Math.max(1,Math.ceil((startMs(r)-now)/60000));\n    countdown.textContent=\"あと\"+minutes+\"分\";\n    section.hidden=false;\n  }\n  document.addEventListener(\"rt:day-loaded\",function(e){\n    var day=e&&e.detail;\n    if(!day||day.date!==todayJst(Date.now())||!Array.isArray(day.races))return;\n    cached=day.races;render();\n  });\n  setInterval(function(){if(!document.hidden)render();},15000);\n  document.addEventListener(\"visibilitychange\",function(){if(!document.hidden)render();});\n})();</script>";
const DAY_ROWS_MARKER='const dayRows=Array.isArray(data.races)?data.races:[];';
export function addNextRacePreview(html:string):string{
  if(html.includes('id="next-target-race"'))return html;
  // Emit from the existing API response after stale-request validation,
  // rather than intercepting window.fetch or issuing an additional request.
  if(!html.includes(DAY_ROWS_MARKER)||!html.includes("</header>")||
    !html.includes("</head>")||!html.includes("</body>"))return html;
  return html.replace(DAY_ROWS_MARKER,
      'document.dispatchEvent(new CustomEvent("rt:day-loaded",{detail:data}));'+DAY_ROWS_MARKER)
    .replace("</head>",NEXT_RACE_CSS+"</head>")
    .replace("</header>","</header>"+NEXT_RACE_HTML)
    .replace("</body>",NEXT_RACE_SCRIPT+"</body>");
}
