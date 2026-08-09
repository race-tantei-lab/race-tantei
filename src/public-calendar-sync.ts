import { fetchJraPage } from "./v1/jra.js";
import { htmlToLines, parseJapaneseDateTime } from "./v1/utils.js";

const VENUE_SLUG: Record<string, string> = {
  "札幌":"sapporo","函館":"hakodate","福島":"fukushima","新潟":"niigata","東京":"tokyo",
  "中山":"nakayama","中京":"chukyo","京都":"kyoto","阪神":"hanshin","小倉":"kokura"
};

interface CalendarRace {
  raceId:string; raceDate:string; venue:string; meetingNo:number; meetingDay:number; raceNo:number;
  raceName:string; conditions:string; surface:string|null; distanceM:number|null;
  startTimeJst:string|null; startTimeUtc:string|null; sourceUrl:string;
}

function jstDateKey(date: Date): string {
  const jst = new Date(date.getTime() + 9 * 60 * 60 * 1000);
  return `${jst.getUTCFullYear()}-${String(jst.getUTCMonth()+1).padStart(2,"0")}-${String(jst.getUTCDate()).padStart(2,"0")}`;
}

function calendarUrl(dateKey:string):string {
  const [year,month,day]=dateKey.split("-");
  return `https://www.jra.go.jp/keiba/calendar${year}/${year}/${Number(month)}/${month}${day}.html`;
}

function startTime(value:string):string|null {
  const m=value.match(/(\d{1,2})時\s*(\d{2})分/);
  return m ? `${String(Number(m[1])).padStart(2,"0")}:${m[2]}` : null;
}

function cleanDetail(parts:string[]):string {
  return parts.join(" ").replace(/\s+/g," ").replace(/レース名・条件/g,"").trim();
}

function raceNameFromDetail(detail:string):string {
  let before=detail;
  const distanceIndex=before.search(/\s\d{1,2},?\d{3}\s*[（(]/);
  if(distanceIndex>0) before=before.slice(0,distanceIndex).trim();
  const grade=before.match(/第\d+回\s*.+?(?:（G[ⅠⅡⅢ123]+）|\(G[123]\))/u);
  if(grade?.[0]) return grade[0].trim();
  const classPattern=/(?:障害)?(?:2歳|3歳|3歳以上)(?:未勝利|新馬|1勝クラス|2勝クラス|3勝クラス|オープン)$/u;
  const classMatch=before.match(classPattern);
  if(classMatch && classMatch.index===0) return before;
  if(classMatch?.index!==undefined && classMatch.index>0) {
    const named=before.slice(0,classMatch.index).trim().replace(/^(?:サマースプリントシリーズ|サマー2000シリーズ)\s*/u,"");
    if(named) return named;
  }
  return before.replace(/^(?:サマースプリントシリーズ|サマー2000シリーズ)\s*/u,"").trim() || "レース";
}

function parseCalendar(html:string,dateKey:string,url:string):CalendarRace[] {
  const lines=htmlToLines(html);
  const out:CalendarRace[]=[];
  let meeting:{no:number;venue:string;day:number}|null=null;
  const [year,month,day]=dateKey.split("-").map(Number);
  for(let i=0;i<lines.length;i+=1){
    const line=lines[i] ?? "";
    const venueMatch=line.match(/^(\d+)回(札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉)(\d+)日$/u);
    if(venueMatch){meeting={no:Number(venueMatch[1]),venue:venueMatch[2],day:Number(venueMatch[3])};continue;}
    if(!meeting) continue;
    const raceMatch=line.match(/^(\d{1,2})レース$/);
    if(!raceMatch) continue;
    const details:string[]=[]; let timeText="";
    for(let j=i+1;j<Math.min(lines.length,i+10);j+=1){
      const next=lines[j] ?? "";
      if(/^(\d+)回(札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉)(\d+)日$/u.test(next) || /^\d{1,2}レース$/.test(next)) break;
      if(/\d{1,2}時\s*\d{2}分/.test(next)){timeText=next;break;}
      if(!/^(?:レース番号|レース名・条件|発走時刻)$/.test(next)) details.push(next);
    }
    const raceNo=Number(raceMatch[1]); const detail=cleanDetail(details); const time=startTime(timeText);
    if(!detail || !time) continue;
    const distance=detail.match(/(\d{1,2},?\d{3})\s*[（(]/)?.[1];
    const surface=/[（(]ダ[）)]/.test(detail)?"ダート":/[（(]芝/.test(detail)||/^障害/.test(detail)?"芝":null;
    const slug=VENUE_SLUG[meeting.venue]; if(!slug) continue;
    out.push({
      raceId:`${dateKey}-${slug}-${String(raceNo).padStart(2,"0")}`,raceDate:dateKey,venue:meeting.venue,
      meetingNo:meeting.no,meetingDay:meeting.day,raceNo,raceName:raceNameFromDetail(detail),conditions:detail,
      surface,distanceM:distance?Number(distance.replace(",","")):null,startTimeJst:time,
      startTimeUtc:parseJapaneseDateTime(year,month,day,time),sourceUrl:url
    });
  }
  return out;
}

async function saveCalendarRaces(db:D1Database,races:CalendarRace[]):Promise<void>{
  if(!races.length)return;
  const statements=races.map(r=>db.prepare(`
    INSERT INTO rt_races (
      race_id,race_date,venue,meeting_no,meeting_day,race_no,race_name,conditions,surface,distance_m,direction,
      start_time_jst,start_time_utc,weather,track_condition,entry_url,result_url,status,entry_updated_at,updated_at
    ) VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?,?,NULL,NULL,?,?, 'scheduled', CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
    ON CONFLICT(race_id) DO UPDATE SET
      race_date=excluded.race_date,venue=excluded.venue,meeting_no=excluded.meeting_no,meeting_day=excluded.meeting_day,
      race_no=excluded.race_no,race_name=CASE WHEN rt_races.race_name IN ('','検索ウィンドウ','検索','出馬表','レース') THEN excluded.race_name ELSE rt_races.race_name END,
      conditions=COALESCE(rt_races.conditions,excluded.conditions),surface=COALESCE(rt_races.surface,excluded.surface),
      distance_m=COALESCE(rt_races.distance_m,excluded.distance_m),start_time_jst=COALESCE(rt_races.start_time_jst,excluded.start_time_jst),
      start_time_utc=COALESCE(rt_races.start_time_utc,excluded.start_time_utc),updated_at=CURRENT_TIMESTAMP
  `).bind(r.raceId,r.raceDate,r.venue,r.meetingNo,r.meetingDay,r.raceNo,r.raceName,r.conditions,r.surface,r.distanceM,r.startTimeJst,r.startTimeUtc,r.sourceUrl,r.sourceUrl));
  await db.batch(statements);
}

async function syncDate(db:D1Database,dateKey:string):Promise<number>{
  const url=calendarUrl(dateKey);
  const page=await fetchJraPage(url);
  const races=parseCalendar(page.html,dateKey,page.url);
  await saveCalendarRaces(db,races);
  return races.length;
}

export async function syncOfficialCalendar(db:D1Database,now=new Date()):Promise<{today:number;yesterday:number}> {
  const todayKey=jstDateKey(now); const yesterdayKey=jstDateKey(new Date(now.getTime()-24*60*60*1000));
  let today=0,yesterday=0;
  try{today=await syncDate(db,todayKey);}catch{/* entry discovery continues */}
  try{yesterday=await syncDate(db,yesterdayKey);}catch{/* historical DB remains available */}
  return {today,yesterday};
}
