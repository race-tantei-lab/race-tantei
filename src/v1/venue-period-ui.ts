/** Responsive year/month ROI explorer for each JRA venue, read-only. */
export const VENUE_PERIOD_UI_CSS="<style>"+
  ".venue-period-card{margin:20px 0 22px;padding:16px;border:1px solid var(--line,#2b3d52);border-radius:18px;background:var(--panel,#101c29)}"+
  ".venue-period-card h2{margin:0;font-size:20px}.venue-period-sub{margin:5px 0 12px;color:var(--muted,#9baec4);font-size:12px;line-height:1.65}"+
  ".venue-period-venue-rail{display:flex;gap:7px;overflow-x:auto;padding:4px 0 10px;scrollbar-width:thin}"+
  ".venue-period-venue-rail button,.venue-period-tabs button,.venue-period-more{border:1px solid var(--line,#2b3d52);border-radius:999px;background:#101f30;color:#dbe9f2;cursor:pointer;padding:8px 12px;font:inherit;font-size:12px;white-space:nowrap}"+
  ".venue-period-venue-rail button[aria-pressed=true],.venue-period-tabs button[aria-pressed=true]{background:#123d35;border-color:#51d0a5;color:#cdfbe7;font-weight:800}"+
  ".venue-period-tabs{display:flex;gap:8px;margin:0 0 12px}.venue-period-tabs button{min-width:86px}"+
  ".venue-period-status{color:var(--muted,#9baec4);font-size:12px;margin:8px 0 12px;line-height:1.6}"+
  ".venue-period-table-wrap{overflow-x:auto}.venue-period-table{width:100%;border-collapse:collapse;min-width:420px;font-variant-numeric:tabular-nums}"+
  ".venue-period-table th{color:var(--muted,#9baec4);font-size:12px;text-align:right;padding:9px 7px;border-bottom:1px solid #314459}"+
  ".venue-period-table td{font-size:13px;padding:10px 7px;text-align:right;border-bottom:1px solid #293a4b}"+
  ".venue-period-table th:first-child,.venue-period-table td:first-child{text-align:left;white-space:nowrap;font-weight:700}"+
  ".venue-period-table .roi{font-weight:900;color:#54d4ad;font-size:17px}"+
  ".venue-period-more{display:block;margin:13px auto 0;padding:9px 22px}"+
  ".venue-period-footnote{color:var(--muted,#9baec4);font-size:11px;line-height:1.7;margin:13px 0 0}"+
  "@media(max-width:650px){.venue-period-card{padding:13px 11px}.venue-period-table{min-width:370px}.venue-period-table th,.venue-period-table td{padding:9px 5px;font-size:11px}.venue-period-table .roi{font-size:15px}}"+
  "</style>";

export const VENUE_PERIOD_UI_HTML='<section class="venue-period-card" id="venue-period-roi" aria-label="会場別の年別月別回収率">'+
  '<h2>会場別・年別／月別回収率</h2>'+
  '<p class="venue-period-sub">会場を選んで年別・月別の成績を確認できます。購入・払戻はライト、精算済みレースのみです。</p>'+
  '<div class="venue-period-venue-rail" aria-label="競馬場を選択" id="venue-period-venues"></div>'+
  '<div class="venue-period-tabs" aria-label="集計期間を選択">'+
  '<button type="button" data-venue-period-mode="month" aria-pressed="true">月別</button>'+
  '<button type="button" data-venue-period-mode="year" aria-pressed="false">年別</button></div>'+
  '<div class="venue-period-status" id="venue-period-status" role="status" aria-live="polite">成績を読み込み中…</div>'+
  '<div class="venue-period-table-wrap"><table class="venue-period-table"><thead><tr><th>期間</th><th>レース数</th><th>購入</th><th>払戻</th><th>回収率</th></tr></thead>'+
  '<tbody id="venue-period-rows"><tr><td colspan="5">読み込み中…</td></tr></tbody></table></div>'+
  '<button type="button" class="venue-period-more" id="venue-period-more" hidden>さらに表示</button>'+
  '<p class="venue-period-footnote">2016/8〜2026/8/9は過去検証、2026/8/10以降は本番の確定馬券の実績です。'+
  '未精算レースは集計に含めません。年・月の回収率は払戻額÷購入額で計算しています。</p>'+
  '</section>';

export const VENUE_PERIOD_UI_SCRIPT="<script>(function(){\n  var root=document.getElementById(\"venue-period-roi\");if(!root)return;\n  var rail=document.getElementById(\"venue-period-venues\"),\n      status=document.getElementById(\"venue-period-status\"),\n      tbody=document.getElementById(\"venue-period-rows\"),\n      more=document.getElementById(\"venue-period-more\"),\n      modes=Array.prototype.slice.call(root.querySelectorAll(\"[data-venue-period-mode]\"));\n  var data=null,venue=\"全会場\",mode=\"month\",limit=12,loading=false;\n  function jp(n){return Number(n).toLocaleString(\"ja-JP\");}\n  function el(tag,txt,cls){var n=document.createElement(tag);n.textContent=txt;if(cls)n.className=cls;return n;}\n  function venueButtons(){\n    if(!data)return;\n    var savedLeft=rail.scrollLeft;rail.replaceChildren();\n    (data.venues||[]).forEach(function(v){\n      var b=el(\"button\",v);b.type=\"button\";b.setAttribute(\"aria-pressed\",String(v===venue));\n      b.addEventListener(\"click\",function(){venue=v;limit=12;venueButtons();render();});\n      rail.appendChild(b);\n    });rail.scrollLeft=savedLeft;\n  }\n  function render(){\n    if(!data)return;\n    modes.forEach(function(b){b.setAttribute(\"aria-pressed\",String(b.getAttribute(\"data-venue-period-mode\")===mode));});\n    var rows=(mode===\"month\"?data.months:data.years).filter(function(x){return x.venue===venue;});\n    var visible=rows.slice(0,limit);tbody.replaceChildren();\n    if(!visible.length){var tr=document.createElement(\"tr\"),td=el(\"td\",\"該当期間の精算済みレースはありません\");td.colSpan=5;tr.appendChild(td);tbody.appendChild(tr);}\n    visible.forEach(function(x){\n      var tr=document.createElement(\"tr\");\n      var items=[mode===\"month\"?x.period.replace(\"-\",\"/\"):x.period+\"年\",\n        jp(x.races)+\"R\",jp(x.stakeYen)+\"円\",jp(x.returnYen)+\"円\",\n        x.roiPct.toFixed(1)+\"%\"];\n      items.forEach(function(t,i){tr.appendChild(el(\"td\",t,i===4?\"roi\":\"\"));});\n      tbody.appendChild(tr);\n    });\n    more.hidden=rows.length<=limit;\n    more.textContent=more.hidden?\"さらに表示\":\"さらに表示（残り\"+jp(rows.length-limit)+\"期間）\";\n  }\n  modes.forEach(function(b){b.addEventListener(\"click\",function(){\n    mode=b.getAttribute(\"data-venue-period-mode\");limit=12;render();\n  });});\n  more.addEventListener(\"click\",function(){limit+=12;render();});\n  function updateStatus(ok){\n    if(!data){status.textContent=ok?\"集計データがありません\":\"成績を取得できません。自動で再試行します。\";return;}\n    var at=new Date(data.updatedAt);\n    var date=Number.isNaN(at.getTime())?\"更新時刻不明\":at.toLocaleString(\"ja-JP\",{timeZone:\"Asia/Tokyo\",month:\"numeric\",day:\"numeric\",hour:\"2-digit\",minute:\"2-digit\"});\n    status.textContent=(ok?\"最終確認 \":\"最新の確認に失敗・前回データ \")+date+\" JST / 本番集計 \"+jp(data.productionRaces)+\"R\";\n  }\n  async function refresh(){\n    if(loading||document.hidden)return;\n    loading=true;\n    try{\n      var reply=await fetch(\"/api/public/venue-period-performance\",{cache:\"no-store\",headers:{\"accept\":\"application/json\"}});\n      if(!reply.ok)throw Error(\"HTTP \"+reply.status);\n      var next=await reply.json();\n      if(next.ok!==true||!Array.isArray(next.months)||!Array.isArray(next.years)||!Array.isArray(next.venues))\n        throw Error(\"INVALID_VENUE_ROI\");\n      data=next;venueButtons();render();updateStatus(true);\n    }catch(e){updateStatus(false);}\n    finally{loading=false;}\n  }\n  refresh();\n  setInterval(refresh,90*1000);\n  document.addEventListener(\"visibilitychange\",function(){if(!document.hidden)refresh();});\n})();</script>";

export function addVenuePeriodExplorer(html:string):string{
  if(html.includes('id="venue-period-roi"'))return html;
  const marker='<section class="daily-performance-wrap"';
  if(!html.includes(marker) || !html.includes("会場別回収率"))return html;
  return html.replace("</head>",VENUE_PERIOD_UI_CSS+"</head>")
    .replace(marker,VENUE_PERIOD_UI_HTML+marker)
    .replace("</body>",VENUE_PERIOD_UI_SCRIPT+"</body>");
}
