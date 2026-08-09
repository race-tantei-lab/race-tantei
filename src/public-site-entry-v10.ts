import publicSite from "./public-site-entry-v9.js";
import type { Env } from "./v1/types.js";

function makeTicketAmountsVisible(html:string):string{
  let out=html.replace(/<th>購入<\/th>/g,"<th>購入額</th>");
  const css=`<style>
  @media(max-width:760px){
    .bet-table{overflow:visible!important}
    .bet-table table{width:100%!important;min-width:0!important;border-collapse:separate!important;border-spacing:0!important}
    .bet-table thead{display:none!important}
    .bet-table tbody{display:grid!important;gap:8px!important}
    .bet-table tr{display:grid!important;grid-template-columns:auto minmax(0,1fr) auto!important;grid-template-areas:"type combo stake" "odds odds payout"!important;column-gap:10px!important;row-gap:6px!important;align-items:center!important;padding:10px 11px!important;border:1px solid var(--line)!important;border-radius:12px!important;background:var(--panel2)!important}
    .bet-table td{display:block!important;padding:0!important;border:0!important;font-size:12px!important;min-width:0!important}
    .bet-table td:nth-child(1){grid-area:type!important;color:var(--muted)!important;font-weight:700!important;white-space:nowrap!important}
    .bet-table td:nth-child(2){grid-area:combo!important;font-size:14px!important;font-weight:800!important;white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important}
    .bet-table td:nth-child(3){grid-area:odds!important;color:var(--muted)!important;white-space:nowrap!important}
    .bet-table td:nth-child(3)::before{content:"オッズ ";font-size:10px!important;color:var(--muted)!important}
    .bet-table td:nth-child(4){grid-area:stake!important;font-size:15px!important;font-weight:900!important;color:#bdf5dc!important;white-space:nowrap!important;text-align:right!important}
    .bet-table td:nth-child(4)::before{content:"購入額 ";display:block!important;font-size:9px!important;font-weight:700!important;color:var(--muted)!important;line-height:1.1!important}
    .bet-table td:nth-child(5){grid-area:payout!important;text-align:right!important;white-space:nowrap!important;color:var(--muted)!important}
    .bet-table td:nth-child(5)::before{content:"払戻 ";font-size:10px!important;color:var(--muted)!important}
    .bet-table td:nth-child(5).plus{color:var(--green)!important;font-weight:800!important}
  }
  </style>`;
  out=out.replace("</head>",`${css}</head>`);
  return out;
}

export default {
  async fetch(request:Request,env:Env,ctx:ExecutionContext):Promise<Response>{
    if(!publicSite.fetch)return new Response("NOT_FOUND",{status:404});
    const response=await publicSite.fetch(request,env,ctx);
    const path=new URL(request.url).pathname;
    if(!path.startsWith("/races/")||!response.ok||!response.headers.get("content-type")?.includes("text/html"))return response;
    try{
      const headers=new Headers(response.headers);headers.delete("content-length");
      return new Response(makeTicketAmountsVisible(await response.text()),{status:response.status,headers});
    }catch{return response;}
  },
  async scheduled(controller:ScheduledController,env:Env,ctx:ExecutionContext):Promise<void>{
    if(publicSite.scheduled)await publicSite.scheduled(controller,env,ctx);
  }
} satisfies ExportedHandler<Env>;
