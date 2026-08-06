import app from "./final-production-entry.js";
import type { Env } from "./v1/types.js";

const LATEST_CLEAN_VALIDATION = {
  generatedAt: "2026-08-06T13:04:41Z",
  modelVersion: "v8.1-clean-data-enriched-ranking-final-holdout",
  productionChanged: false,
  promotionEligible: false,
  data: {
    finishedRaces: 7695,
    firstDate: "2024-05-04",
    lastDate: "2026-08-02",
    invalidRaces: 0
  },
  guardrails: {
    selectedRacesPerVenueDay: 5,
    budgets: {
      ライト: 2000,
      スタンダード: 5000,
      プレミアム: 10000
    },
    finalHoldoutStart: "2026-05",
    currentRaceMarketRemoved: true
  },
  courses: [
    { course: "ライト", races: 400, roiPct: 73.5890625, hitRatePct: 54.5, profitYen: -169030 },
    { course: "スタンダード", races: 400, roiPct: 63.09464285714286, hitRatePct: 56.75, profitYen: -620010 },
    { course: "プレミアム", races: 400, roiPct: 74.92130681818182, hitRatePct: 38.75, profitYen: -882770 }
  ]
} as const;

const INTERACTION_SCRIPT = `<script>(()=>{
  const selectDay=(value)=>{
    document.querySelectorAll('[data-day-tab]').forEach((button)=>button.setAttribute('aria-selected',String(button.getAttribute('data-day-tab')===value)));
    document.querySelectorAll('[data-day-panel]').forEach((panel)=>{panel.hidden=panel.getAttribute('data-day-panel')!==value;});
    const active=document.querySelector('[data-day-panel="'+CSS.escape(value)+'"]');
    if(active){
      const firstVenue=active.querySelector('[data-venue-tab]');
      if(firstVenue) selectVenue(active,firstVenue.getAttribute('data-venue-tab')||'');
      const buy=active.querySelector('[data-filter="buy"]');
      if(buy) selectFilter(active,'buy');
    }
  };
  const selectVenue=(panel,value)=>{
    panel.querySelectorAll('[data-venue-tab]').forEach((button)=>button.setAttribute('aria-selected',String(button.getAttribute('data-venue-tab')===value)));
    panel.querySelectorAll('[data-venue-panel]').forEach((section)=>{section.hidden=section.getAttribute('data-venue-panel')!==value;});
  };
  const selectFilter=(panel,value)=>{
    panel.querySelectorAll('[data-filter]').forEach((button)=>button.setAttribute('aria-selected',String(button.getAttribute('data-filter')===value)));
    panel.querySelectorAll('.race-card').forEach((card)=>{
      const category=card.getAttribute('data-race-category')||'';
      const selected=card.getAttribute('data-race-selected')==='true';
      card.hidden=value==='buy'?!selected:value==='finished'?!category.includes('finished'):false;
    });
  };
  document.addEventListener('click',(event)=>{
    const target=event.target instanceof Element?event.target.closest('button'):null;
    if(!target)return;
    const day=target.getAttribute('data-day-tab');
    if(day){selectDay(day);return;}
    const panel=target.closest('[data-day-panel]');
    if(!panel)return;
    const venue=target.getAttribute('data-venue-tab');
    if(venue!==null){selectVenue(panel,venue);return;}
    const filter=target.getAttribute('data-filter');
    if(filter!==null)selectFilter(panel,filter);
  });
  const first=document.querySelector('[data-day-tab]');
  if(first)selectDay(first.getAttribute('data-day-tab')||'');
})();</script>`;

function formatYen(value: number): string {
  return `${value < 0 ? "−" : "+"}¥${Math.abs(value).toLocaleString("ja-JP")}`;
}

function validationPage(): Response {
  const cards = LATEST_CLEAN_VALIDATION.courses.map((row) => `
    <article class="card">
      <b>${row.course}</b>
      <strong>${row.roiPct.toFixed(1)}%</strong>
      <span>最終未見期間 ${row.races}R</span>
      <span>的中率 ${row.hitRatePct.toFixed(1)}%</span>
      <em>${formatYen(row.profitYen)}</em>
    </article>`).join("");
  const budgets = LATEST_CLEAN_VALIDATION.guardrails.budgets;
  const body = `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#07111b"><title>全期間検証｜レース探偵</title><style>
  :root{color-scheme:dark;--bg:#07111b;--panel:#101c29;--line:#2b3d52;--text:#f2f5f8;--muted:#9baec4;--red:#ff7d77;--green:#51d0a5;--warn:#f2d48d}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}.wrap{max-width:960px;margin:auto;padding:20px 16px 48px}.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:22px}.brand{font-size:27px;font-weight:900;color:var(--green);text-decoration:none}.top nav{display:flex;gap:8px}.top nav a{color:var(--text);text-decoration:none;border:1px solid var(--line);border-radius:999px;padding:9px 13px}.hero,.notice,.card,.facts{border:1px solid var(--line);border-radius:18px;background:var(--panel)}.hero{padding:20px}.hero h1{margin:0 0 10px}.hero p{margin:7px 0;color:var(--muted);line-height:1.7}.notice{margin:14px 0;padding:15px;border-color:#7a3737;background:#2a1619;color:#ffd3d0;line-height:1.7}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:16px 0}.card{padding:18px}.card b,.card span,.card em{display:block}.card strong{display:block;font-size:34px;color:var(--red);margin:8px 0}.card span{color:var(--muted);margin-top:5px}.card em{font-style:normal;color:var(--red);margin-top:9px}.facts{padding:16px;line-height:1.9}.facts b{color:var(--green)}.facts code{color:var(--warn);word-break:break-all}@media(max-width:720px){.grid{grid-template-columns:1fr}}
  </style></head><body><main class="wrap"><header class="top"><a class="brand" href="/">レース探偵</a><nav><a href="/performance">成績</a><a href="/validation">検証</a></nav></header><section class="hero"><h1>修復後データの全期間検証</h1><p><b>${LATEST_CLEAN_VALIDATION.modelVersion}</b></p><p>${LATEST_CLEAN_VALIDATION.data.firstDate}〜${LATEST_CLEAN_VALIDATION.data.lastDate}の全${LATEST_CLEAN_VALIDATION.data.finishedRaces.toLocaleString("ja-JP")}レースを使用し、対象月より前のデータだけで学習・選定しました。</p></section><section class="notice"><b>本番切替判定：不合格</b><br>最終未見期間で全コースが目標200%を下回ったため、この候補は本番へ切り替えていません。古い高回収率の検証値は表示しません。</section><section class="grid">${cards}</section><section class="facts"><b>本番運用</b><br>会場ごと5レースを選び、選択した各レースでライト¥${budgets.ライト.toLocaleString("ja-JP")}・スタンダード¥${budgets.スタンダード.toLocaleString("ja-JP")}・プレミアム¥${budgets.プレミアム.toLocaleString("ja-JP")}を使用します。<br><b>データ監査</b><br>人気順位・単勝オッズの異常レースは${LATEST_CLEAN_VALIDATION.data.invalidRaces}件です。<br><b>本番モデル</b><br>合格モデルが出るまでは現行モデルを維持し、検証不合格モデルへの自動切替は行いません。</section></main></body></html>`;
  return new Response(body, {
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "x-race-ui-version": "clean-validation-v8-1"
    }
  });
}

function validationJson(): Response {
  return new Response(JSON.stringify(LATEST_CLEAN_VALIDATION, null, 2), {
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "x-robots-tag": "noindex, nofollow"
    }
  });
}

async function withInteractions(response: Response): Promise<Response> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("text/html")) return response;
  const source = await response.text();
  const body = source.includes("</body>") ? source.replace("</body>", `${INTERACTION_SCRIPT}</body>`) : `${source}${INTERACTION_SCRIPT}`;
  const headers = new Headers(response.headers);
  headers.set("cache-control", "no-store, max-age=0");
  headers.set("content-length", String(new TextEncoder().encode(body).length));
  headers.set("x-race-ui-version", "final-v5-all-routes-unified");
  return new Response(body, { status: response.status, statusText: response.statusText, headers });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!app.fetch) return new Response("NOT_FOUND", { status: 404 });
    const url = new URL(request.url);
    if (url.pathname === "/validation") return validationPage();
    if (url.pathname === "/api/validation/latest") return validationJson();
    const legacyDetail = url.pathname.startsWith("/history/") || url.pathname.startsWith("/races/");
    const effectiveRequest = legacyDetail
      ? new Request(new URL("/", url), request)
      : request;
    return withInteractions(await app.fetch(effectiveRequest, env, ctx));
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (app.scheduled) await app.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
