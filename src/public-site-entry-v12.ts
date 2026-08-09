import publicSite from "./public-site-entry-v11.js";
import type { Env } from "./v1/types.js";

type VenueRoi = {
  venue: string;
  settledRaces: number;
  light: number;
  standard: number;
  premium: number;
};

const VENUE_ROI: VenueRoi[] = [
  { venue: "札幌", settledRaces: 165, light: 86.7, standard: 84.4, premium: 86.8 },
  { venue: "函館", settledRaces: 170, light: 221.9, standard: 251.3, premium: 237.0 },
  { venue: "福島", settledRaces: 240, light: 336.0, standard: 321.2, premium: 321.3 },
  { venue: "新潟", settledRaces: 315, light: 164.4, standard: 157.9, premium: 159.8 },
  { venue: "東京", settledRaces: 505, light: 364.0, standard: 379.2, premium: 380.1 },
  { venue: "中山", settledRaces: 425, light: 449.2, standard: 443.6, premium: 444.0 },
  { venue: "中京", settledRaces: 330, light: 318.3, standard: 310.4, premium: 303.2 },
  { venue: "京都", settledRaces: 530, light: 318.3, standard: 327.9, premium: 328.1 },
  { venue: "阪神", settledRaces: 310, light: 188.9, standard: 186.9, premium: 192.1 },
  { venue: "小倉", settledRaces: 235, light: 279.2, standard: 264.2, premium: 262.7 }
];

function roiClass(value: number): string {
  return value >= 100 ? "venue-roi-plus" : "venue-roi-minus";
}

function venueRoiHtml(): string {
  const cards = VENUE_ROI.map((row) => `
    <article class="venue-roi-card">
      <div class="venue-roi-head"><b>${row.venue}</b><span>${row.settledRaces}R</span></div>
      <div class="venue-roi-row"><span>ライト</span><strong class="${roiClass(row.light)}">${row.light.toFixed(1)}%</strong></div>
      <div class="venue-roi-row"><span>スタンダード</span><strong class="${roiClass(row.standard)}">${row.standard.toFixed(1)}%</strong></div>
      <div class="venue-roi-row"><span>プレミアム</span><strong class="${roiClass(row.premium)}">${row.premium.toFixed(1)}%</strong></div>
    </article>`).join("");

  return `<div class="section-title venue-roi-title"><h2>会場別回収率</h2><span class="muted">全期間・3,225R</span></div><div class="venue-roi-rail">${cards}</div>`;
}

function injectVenueRoi(html: string): string {
  const css = `<style>
    .venue-roi-title{margin-top:20px!important}
    .venue-roi-rail{display:flex;gap:10px;overflow-x:auto;padding:2px 0 10px;scrollbar-width:thin}
    .venue-roi-card{flex:0 0 205px;border:1px solid var(--line);background:var(--panel);border-radius:16px;padding:13px}
    .venue-roi-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px}
    .venue-roi-head b{font-size:18px}.venue-roi-head span{font-size:12px;color:var(--muted)}
    .venue-roi-row{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:6px 0;border-top:1px solid rgba(43,61,82,.55);font-size:12px}
    .venue-roi-row span{color:var(--muted)}.venue-roi-row strong{font-size:15px}
    .venue-roi-plus{color:var(--green)}.venue-roi-minus{color:var(--red)}
    @media(max-width:760px){.venue-roi-card{flex-basis:190px}.venue-roi-head b{font-size:17px}}
  </style>`;
  const anchor = `<div class="section-title"><h2 id="selected-date">`;
  const withCss = html.replace("</head>", `${css}</head>`);
  return withCss.includes(anchor) ? withCss.replace(anchor, `${venueRoiHtml()}${anchor}`) : withCss;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!publicSite.fetch) return new Response("NOT_FOUND", { status: 404 });
    const response = await publicSite.fetch(request, env, ctx);
    const path = new URL(request.url).pathname;
    if (path !== "/" || !response.ok || !response.headers.get("content-type")?.includes("text/html")) return response;
    try {
      const headers = new Headers(response.headers);
      headers.delete("content-length");
      return new Response(injectVenueRoi(await response.text()), { status: response.status, headers });
    } catch {
      return response;
    }
  },
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (publicSite.scheduled) await publicSite.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
