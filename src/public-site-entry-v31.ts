import publicSite from "./public-site-entry-v30.js";
import type { Env } from "./v1/types.js";

const UI_VERSION = "ten-year-completed-public-v31-stable-next-bet-20260816";

function jstDate(now = new Date()): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

async function dailySelectionExists(env: Env): Promise<boolean | null> {
  try {
    const date = jstDate();
    const row = await env.DB.prepare(
      "SELECT 1 AS ok FROM rt_system_state WHERE state_key=? LIMIT 1",
    ).bind(`final_daily_selection:${date}`).first<{ ok: number }>();
    return Boolean(row?.ok);
  } catch (error) {
    console.error("HOME_NEXT_BET_SELECTION_CHECK_FAILED", error);
    return null;
  }
}

function fallbackNextBet(selectionExists: boolean | null): string {
  if (selectionExists === true) {
    return `<section class="home-next-release home-next-release-empty" aria-label="次の買い目">
      <span>次の買い目</span>
      <div class="home-next-release-copy"><b>本日の買い目公開は終了</b></div>
      <small>次回は次の開催日の対象決定後に表示</small>
    </section>`;
  }
  if (selectionExists === false) {
    return `<section class="home-next-release home-next-release-empty" aria-label="次の買い目">
      <span>次の買い目</span>
      <div class="home-next-release-copy"><b>対象レース決定後に表示</b></div>
      <small>当日8:00以降に対象レースを決定</small>
    </section>`;
  }
  return `<section class="home-next-release home-next-release-empty" aria-label="次の買い目">
    <span>次の買い目</span>
    <div class="home-next-release-copy"><b>次の買い目を確認中</b></div>
    <small>ページを再読み込みすると更新されます</small>
  </section>`;
}

async function keepNextBetSlot(response: Response, env: Env, path: string): Promise<Response> {
  if (path !== "/" || !response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;

  let html = await response.text();
  if (!html.includes('class="home-next-release')) {
    const selectionExists = await dailySelectionExists(env);
    const slot = fallbackNextBet(selectionExists);
    if (html.includes('<details class="home-publish-flow home-publish-details">')) {
      html = html.replace('<details class="home-publish-flow home-publish-details">', `${slot}<details class="home-publish-flow home-publish-details">`);
    } else {
      html = html.replace(/(<div class="section-title"><h2>累計回収率<\/h2>)/, `${slot}$1`);
    }
  }

  html = html.replace(
    "</head>",
    `<style>.home-next-release-empty{border-color:var(--line);background:var(--panel)}.home-next-release-copy{display:flex;align-items:baseline;min-width:0}.home-next-release-empty b{font-size:14px;color:var(--text)}@media(max-width:760px){.home-next-release-copy{grid-column:2}.home-next-release-empty small{grid-column:2}}</style></head>`,
  );

  const headers = new Headers(response.headers);
  headers.delete("content-length");
  headers.set("x-race-ui-version", UI_VERSION);
  return new Response(html, { status: response.status, statusText: response.statusText, headers });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const path = new URL(request.url).pathname;
    const response = await publicSite.fetch(request, env, ctx);
    return keepNextBetSlot(response, env, path);
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  },
} satisfies ExportedHandler<Env>;
