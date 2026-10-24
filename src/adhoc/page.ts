/**
 * Isolated, read-only-input ad-hoc prediction UI.
 * This HTML is static; dynamic user content always goes through textContent.
 */
export function adhocPage(): Response {
  const html = String.raw\`<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#07131d"><title>指定レース予想｜レース探偵</title>
<style>
:root{color-scheme:dark;--bg:#07131d;--panel:#112431;--ink:#eaf6f8;--muted:#9eb6c2;--line:#254251;--teal:#42dfba;--gold:#f8d28d;--bad:#ff9d91}
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Noto Sans JP","Segoe UI",sans-serif;background:radial-gradient(ellipse at 90% 0%,#173f45 0%,transparent 42%),var(--bg);color:var(--ink);min-height:100vh}
.wrap{max-width:910px;margin:auto;padding:18px 18px 80px}header{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:8px 0 30px;flex-wrap:wrap}
.brand{font-size:21px;font-weight:850;letter-spacing:-.06em;text-decoration:none;color:var(--ink)}nav{display:flex;gap:10px;flex-wrap:wrap}nav a{color:var(--muted);text-decoration:none;font-size:13px;border:1px solid var(--line);padding:8px 12px;border-radius:99px}nav a[aria-current]{color:var(--teal);border-color:var(--teal)}
.eyebrow{color:var(--teal);font-size:12px;font-weight:800;letter-spacing:.14em}.hero h1{font-size:clamp(29px,5vw,49px);letter-spacing:-.06em;line-height:1.16;margin:9px 0 16px}.hero p{line-height:1.8;color:var(--muted);font-size:14px;max-width:730px}
.layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:18px;margin-top:28px}.panel{border:1px solid var(--line);border-radius:20px;background:linear-gradient(155deg,#122b38,#0c202d);padding:23px;box-shadow:0 18px 38px #0002}
.panel h2{margin:0 0 19px;font-size:19px}.panel label{display:block;font-size:12px;font-weight:800;color:var(--muted);margin:15px 0 8px}
select,button{font:inherit}select{width:100%;background:#071b25;border:1px solid #41616b;border-radius:12px;color:var(--ink);padding:14px;outline:none;min-height:50px}select:focus{border-color:var(--teal)}button{width:100%;border:0;border-radius:12px;background:var(--teal);color:#05201c;font-size:15px;font-weight:850;padding:15px;margin-top:18px;cursor:pointer;min-height:50px}button:disabled{cursor:not-allowed;opacity:.45}.info{font-size:12px;line-height:1.8;color:var(--muted);margin-top:14px}
.state{display:flex;align-items:center;gap:9px;color:var(--gold);font-weight:750;font-size:13px;margin-bottom:17px}.dot{width:9px;height:9px;border-radius:99px;background:currentColor}.prediction{display:none}.prediction.visible{display:block}.top{border-radius:16px;background:#153b3b;padding:20px 18px;margin-bottom:14px;border:1px solid #2b6a60}.top small{color:#b5d3cf}.top strong{display:block;font-size:27px;margin-top:7px}.top span{color:var(--teal);font-size:20px;font-weight:850}
.bets{display:grid;grid-template-columns:1fr 1fr;gap:10px}.bet{border:1px solid var(--line);border-radius:14px;padding:13px;background:#0c1d29}.bet small{display:block;color:var(--muted);font-size:11px}.bet strong{display:block;font-size:18px;margin:8px 0}.bet span{font-size:12px;color:var(--gold)}
table{width:100%;border-collapse:collapse;margin-top:14px;font-size:13px}th,td{padding:10px 4px;border-bottom:1px solid var(--line);text-align:left}td:last-child,th:last-child{text-align:right}th{color:var(--muted);font-weight:650}
.note{border-left:2px solid var(--gold);padding:10px 13px;color:var(--muted);line-height:1.8;font-size:12px;margin-top:15px;background:#1d2a2e}
#error{color:var(--bad);font-size:13px;line-height:1.6;min-height:22px;margin-top:12px}#statusText{line-height:1.9;color:var(--muted);font-size:14px}footer{border-top:1px solid var(--line);margin-top:40px;padding-top:20px;color:var(--muted);font-size:12px;line-height:1.9}
@media(max-width:690px){.layout{grid-template-columns:1fr}.panel{padding:19px}.hero h1{font-size:32px}}
</style></head><body><main class="wrap">
<header><a href="/" class="brand">レース探偵</a><nav><a href="/">自動予想</a><a href="/adhoc" aria-current="page">指定レース予想</a><a href="/performance">成績</a></nav></header>
<section class="hero"><span class="eyebrow">RACE ON DEMAND · BETA</span><h1>選定外のレースも、<br>同じモデルで予想する。</h1><p>レース探偵の学習済みモデル、30日学習補正、JRA公式オッズを使った指定レース予想。通常の自動選定・買い目・精算とは完全に分離しています。</p></section>
<section class="layout"><div class="panel"><h2>レースを選択</h2>
<label for="date">開催日</label><select id="date" aria-label="開催日"><option value="">取得中…</option></select>
<label for="race">レース</label><select id="race" aria-label="レース"><option value="">開催日を選んでください</option></select>
<button id="request" disabled>このレースを予想する</button><div id="error" role="alert"></div>
<div class="info">発走75分前まで受付（予定数に達すると終了）。計算はGitHub Actionsで実行するため、結果反映まで時間がかかる場合があります。発走15分前までに完了できなければ未成立として扱います。</div>
<div class="note">無料枠を保護するため、1開催日あたり最大3レース。処理余力が足りない場合は自動で停止します。同一レースの再依頼は新規計算せず結果を共有します。</div>
</div><div class="panel" aria-live="polite"><h2>予想ステータス</h2><div class="state"><span class="dot" aria-hidden="true"></span><span id="state">待機中</span></div><p id="statusText">レースを選択すると、予想の有無を確認できます。</p>
<div id="prediction" class="prediction"><div class="top"><small>モデル内の最上位馬</small><strong id="bestHorse"></strong><span id="bestProb"></span></div><div class="bets" id="bets"></div><h3>モデル確率ランキング</h3><table><thead><tr><th>順位</th><th>馬番 / 馬名</th><th>勝利確率</th></tr></thead><tbody id="ranking"></tbody></table><div class="note" id="provenance"></div></div>
</div></section>
<footer>指定レースの結果は独立保存され、自動選定対象数・過去の回収率・公式予想記録へ加算されません。確率は統計モデル上の推定で、利益や的中を保証しません。発走後の予想生成や結果を用いた後付け計算は行いません。</footer>
</main><script>
(function(){
 const $=id=>document.getElementById(id);
 let races=[], current=null, poll=null, requestRace="";
 const show=(state,message)=>{$("state").textContent=state;$("statusText").textContent=message};
 const err=m=>{$("error").textContent=m};
 const fmt=n=>Number(n*100).toFixed(2)+"%";
 const cell=(tr,text)=>{const t=document.createElement("td");t.textContent=String(text);tr.append(t)};
 function render(r){
  const p=r.result;
  if(!p){$("prediction").classList.remove("visible");return}
  $("prediction").classList.add("visible");
  const sorted=(p.ranking||[]).slice().sort((a,b)=>b.winProbability-a.winProbability);
  if(sorted.length){$("bestHorse").textContent=sorted[0].horseNo+" "+sorted[0].horseName;$("bestProb").textContent=fmt(sorted[0].winProbability)}
  $("bets").replaceChildren();
  for(const b of p.tickets||[]){const x=document.createElement("div");x.className="bet";
   const tag=document.createElement("small");tag.textContent=b.betType;const strong=document.createElement("strong");strong.textContent=b.combination;
   const odds=document.createElement("span");odds.textContent="公式オッズ "+b.officialOdds+"倍";x.append(tag,strong,odds);$("bets").append(x)}
  $("ranking").replaceChildren();
  sorted.forEach((r,i)=>{const tr=document.createElement("tr");cell(tr,i+1);cell(tr,r.horseNo+" "+r.horseName);cell(tr,fmt(r.winProbability));$("ranking").append(tr)});
  $("provenance").textContent="生成 "+p.generatedAtJst+" / 56特徴量・学習済み500本の決定木 / 直近30日の学習補正 / JRA公式オッズ / 馬体重 "+(p.officialBodyWeightApplied?"反映済み":"発表前または未取得");
 }
 function formatRow(x){return x.venue+" "+String(x.raceNo).padStart(2,"0")+"R　"+x.raceName+"　"+x.startTimeJst}
 function selectRace(){
  clearInterval(poll);poll=null;requestRace=$("race").value;$("prediction").classList.remove("visible");err("");
  const chosen=races.find(x=>x.raceId===requestRace);if(!chosen){$("request").disabled=true;show("待機中","レースを選んでください。");return}
  $("request").disabled=!chosen.accepting;
  show("確認中","過去の依頼を確認しています。");status();
  poll=setInterval(status,30000);
 }
 async function status(){
  if(!requestRace)return;
  try{const r=await fetch("/api/adhoc/status?raceId="+encodeURIComponent(requestRace),{cache:"no-store"});const j=await r.json();if(requestRace!==j.raceId)return;
   if(j.status==="ready"){show("予想完成","このレースの予想が完成しました。");render(j);clearInterval(poll);poll=null}
   else if(j.status==="queued"||j.status==="running"){show(j.status==="queued"?"受付済み":"計算中","無料枠を確認しながら予想しています。発走前に完了しない場合は公開されません。")}
   else if(j.status==="failed"||j.status==="expired"){show("予想未成立",j.message||"締切または無料枠の制約により、予想を公開できませんでした。");clearInterval(poll);poll=null}
   else show("未依頼","レースを指定して予想を依頼できます。");
  }catch(e){show("取得失敗","通信が不安定です。自動的に再確認します。")}
 }
 function dates(){
  const d=[...new Set(races.map(x=>x.raceDate))];$("date").replaceChildren();for(const x of d){const op=document.createElement("option");op.value=x;op.textContent=x;$("date").append(op)}
  if(!d.length){const op=document.createElement("option");op.textContent="受付可能な開催日がありません";$("date").append(op)}
  populate()
 }
 function populate(){
  const day=$("date").value;const list=races.filter(x=>x.raceDate===day).sort((a,b)=>a.venue.localeCompare(b.venue,"ja")||a.raceNo-b.raceNo);
  $("race").replaceChildren();for(const x of list){const op=document.createElement("option");op.value=x.raceId;op.textContent=formatRow(x)+(x.accepting?"":"（受付終了）");$("race").append(op)}
  if(!list.length){const op=document.createElement("option");op.textContent="対象レースがありません";$("race").append(op)}
  selectRace()
 }
 $("date").addEventListener("change",populate);$("race").addEventListener("change",selectRace);
 $("request").addEventListener("click",async()=>{
  const id=$("race").value;if(!id)return;$("request").disabled=true;err("");
  try{const r=await fetch("/api/adhoc/request",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({raceId:id})});const j=await r.json();
   if(!r.ok){err(j.message||"受け付けできませんでした。");return}
   show("受付済み","依頼を受け付けました。準備ができ次第、ここに表示します。");await status();
  }catch(e){err("通信に失敗しました。しばらくして再確認してください。")}
  finally{const x=races.find(z=>z.raceId===id);$("request").disabled=!x?.accepting}
 });
 fetch("/api/adhoc/races",{cache:"no-store"}).then(x=>{if(!x.ok)throw Error("API");return x.json()}).then(j=>{races=j.races||[];dates()}).catch(()=>{err("出走表を取得できません。少し経ってから再読み込みしてください。");$("date").replaceChildren()});
})();
</script></body></html>\`;
  return new Response(html, {
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "public, max-age=60",
      "x-content-type-options": "nosniff",
      "x-robots-tag": "noindex, nofollow",
      "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self';",
    },
  });
}
