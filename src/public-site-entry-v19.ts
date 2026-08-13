import publicSite from "./public-site-entry-v18.js";
import type { Env } from "./v1/types.js";

function timingBlock(): string {
  return `
  <details class="data-timing">
    <summary><b>自動取得のタイミング</b><span>JST・タップで表示</span></summary>
    <div class="data-timing-body">
      <p><b>開催・出馬情報</b><span>同期処理は5分ごとに起動。新しい開催の探索は木〜日曜は90分ごと、土日は8:00〜20:59に20分ごとです。</span></p>
      <p><b>登録済みレース</b><span>発走24時間超前は3時間ごと、24〜3時間前は1時間ごと、3時間〜45分前は15分ごと、45分前以降は5分ごとに更新します。</span></p>
      <p><b>買い目</b><span>土・日・月の8:00〜19:00に10分ごとに確認し、対象レースは発走45〜15分前にJRA公式オッズを取得して固定します。</span></p>
      <p><b>結果・払戻</b><span>発走約4分後から結果を確認し、取得できなければ次回以降も再試行。払戻取得後に保存済み買い目と自動照合して反映します。</span></p>
    </div>
  </details>`;
}

function enhanceConditions(html: string): string {
  const anchor = '<div class="section-title"><h2>① 5レースをどう選ぶか</h2><span class="muted">12R → 5R</span></div>';
  if (!html.includes(anchor) || html.includes('class="data-timing"')) return html;
  const css = `<style>
    .data-timing{margin:12px 0 4px;border:1px solid var(--line);border-radius:12px;background:var(--panel);overflow:hidden}
    .data-timing summary{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 12px;cursor:pointer;list-style:none}
    .data-timing summary::-webkit-details-marker{display:none}.data-timing summary b{font-size:13px}.data-timing summary span{font-size:10px;color:var(--muted)}
    .data-timing-body{padding:0 12px 10px;border-top:1px solid var(--line)}
    .data-timing-body p{display:grid;grid-template-columns:105px minmax(0,1fr);gap:10px;margin:0;padding:8px 0;border-bottom:1px solid rgba(43,61,82,.45);font-size:11px;line-height:1.55}
    .data-timing-body p:last-child{border-bottom:0}.data-timing-body p>b{font-size:11px}.data-timing-body p>span{color:var(--muted)}
    @media(max-width:760px){.data-timing{margin-top:9px}.data-timing summary{padding:9px 10px}.data-timing-body{padding:0 10px 8px}.data-timing-body p{grid-template-columns:82px minmax(0,1fr);gap:8px;font-size:10px}}
  </style>`;
  return html.replace("</head>", `${css}</head>`).replace(anchor, `${timingBlock()}${anchor}`);
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    if (new URL(request.url).pathname !== "/conditions" || !response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
    try {
      const headers = new Headers(response.headers);
      headers.delete("content-length");
      headers.set("cache-control", "no-store, max-age=0");
      headers.set("x-race-ui-version", "ten-year-completed-public-v19-timing-20260813");
      return new Response(enhanceConditions(await response.text()), { status: response.status, headers });
    } catch {
      return response;
    }
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
