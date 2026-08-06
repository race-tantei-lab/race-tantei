import app from "./final-production-entry.js";
import type { Env } from "./v1/types.js";

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
