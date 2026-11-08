/** Read-only rendering of genuine before-T15 research snapshots.
 * This is NOT a new money-betting recommendation. It neither alters
 * public bet tickets nor claims that modeled 500% actual ROI is attainable.
 */
type ShadowBet={
  betType: string; combination:string; stakeYen:number;
  conservativeOfficialOdds:number; modelProbability:number;
  expectedReturnPerYen:number
};
type Shadow={
  policy:string; researchOnly:boolean; notActualJraRoi:boolean;
  minimumModeledHitPct:number; modeledTwoTicketHitPct:number;
  modeledExpectedRoiPct:number; stakeYen:number; oddsFetchedAt:string;
  startTimeUtc:string; tickets:ShadowBet[];
};
type FinalPreview={ oddsFetchedAt?:string; roiFirstResearch?:Shadow|null };
const TYPES=new Set(["単勝","ワイド","馬連","馬単","3連複","3連単"]);
function esc(s:unknown):string {
  return String(s??"").replace(/[&<>"']/g,ch=>({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  }[ch]??ch));
}
function valid(s:Shadow,final:FinalPreview,startTimeUtc:string):boolean {
  if(s.policy!=="roi_first_jra_official_model_ev_v1"
    ||s.researchOnly!==true||s.notActualJraRoi!==true
    ||s.minimumModeledHitPct!==20||s.stakeYen!==2000
    ||!Number.isFinite(s.modeledExpectedRoiPct)||s.modeledExpectedRoiPct<0
    ||!Number.isFinite(s.modeledTwoTicketHitPct)
    ||s.modeledTwoTicketHitPct<20||s.modeledTwoTicketHitPct>100
    ||s.oddsFetchedAt!==final.oddsFetchedAt||s.startTimeUtc!==startTimeUtc
    ||!Array.isArray(s.tickets)||s.tickets.length!==2)return false;
  const observed=Date.parse(s.oddsFetchedAt), start=Date.parse(startTimeUtc);
  if(!Number.isFinite(start)||!Number.isFinite(observed)
    ||observed>start-15*60*1000)return false;
  if(s.tickets[0]?.betType===s.tickets[1]?.betType)return false;
  if(s.tickets.reduce((n,t)=>n+t.stakeYen,0)!==2000)return false;
  for(const t of s.tickets){
    if(!TYPES.has(t.betType)||typeof t.combination!=="string"
      ||!/^\d{1,2}(?:-\d{1,2}){0,2}$/.test(t.combination)
      ||!Number.isInteger(t.stakeYen)||t.stakeYen<100||t.stakeYen%100
      ||!Number.isFinite(t.modelProbability)||t.modelProbability<=0||t.modelProbability>1
      ||!Number.isFinite(t.conservativeOfficialOdds)||t.conservativeOfficialOdds<1
      ||!Number.isFinite(t.expectedReturnPerYen)||t.expectedReturnPerYen<=0
      ||Math.abs(t.modelProbability*t.conservativeOfficialOdds-t.expectedReturnPerYen)>1e-6
    )return false;
  }
  return true;
}
function yen(n:number):string{return Math.round(n).toLocaleString("ja-JP")+"円";}
export function highReturnResearchView(finalRaw:string|null,startTimeUtc:string|null):string {
  const unavailable='<p class="locked-note">発走15分前以前のJRA公式オッズに基づく研究候補は確認できません。数字や馬券を後付けで作成しません。</p>';
  const heading='<div class="section-title"><h2>高配当シミュレーション</h2><span class="status target">研究用・購入推奨ではありません</span></div>';
  const notice='<p class="locked-note">「回収率500%」は2,000円に対し払戻10,000円という<b>的中時の条件</b>です。実現見込みや期待回収率500%を示すものではありません。公開される既存の予想・購入額・成績には一切反映されません。</p>';
  const wrap=(inside:string)=>'<section class="card reason-panel" data-race-panel="high-return" hidden>'+heading+notice+inside+'</section>';
  if(!finalRaw||!startTimeUtc)return wrap(unavailable);
  try{
    const f=JSON.parse(finalRaw) as FinalPreview,s=f.roiFirstResearch;
    if(!s||!valid(s,f,startTimeUtc))return wrap(unavailable);
    const maxSingle=Math.max(...s.tickets.map(t=>t.stakeYen*t.conservativeOfficialOdds));
    const hit500=maxSingle>=10000;
    const date=new Date(Date.parse(s.oddsFetchedAt)+9*3600000).toISOString().slice(0,16).replace("T"," ");
    const rows=s.tickets.map(t=>{
      const possible=t.stakeYen*t.conservativeOfficialOdds;
      return '<tr><td>'+esc(t.betType)+'</td><td>'+esc(t.combination)+'</td>'
        +'<td>'+yen(t.stakeYen)+'</td><td>'+t.conservativeOfficialOdds.toFixed(1)+'倍</td>'
        +'<td>'+yen(possible)+'</td><td>'+(100*possible/2000).toFixed(0)+'%</td></tr>';
    }).join("");
    const result='<p class="locked-note">'+(hit500?
      '当時の参考オッズで、<b>いずれか1点の的中のみでも払戻10,000円以上となる組合せがあります。</b>':
      '当時の参考オッズでは、1点だけの的中で払戻10,000円を超えるとは計算できません。')
      +' 未的中時の払戻は0円、確定払戻は参考オッズと異なる場合があります。</p>';
    return wrap('<p class="locked-note">JRA公式オッズの取得記録：'+esc(date)+' JST（発走15分より前）</p>'
      +'<div class="bet-table"><table><thead><tr><th>券種</th><th>組合せ</th><th>仮想購入額</th><th>取得時参考オッズ（下限）</th><th>的中時参考払戻</th><th>参考回収率</th></tr></thead><tbody>'+rows+'</tbody></table></div>'
      +result
      +'<p class="locked-note">2券種の<strong>モデル仮説的中率</strong>：'+s.modeledTwoTicketHitPct.toFixed(2)
      +'% ／ <strong>未校正の理論期待回収率</strong>：'+s.modeledExpectedRoiPct.toFixed(2)
      +'%（過去の実回収率ではありません）。勝率・払戻予測の校正、実現可能性、当日利益は未検証です。</p>');
  }catch{return wrap(unavailable);}
}
