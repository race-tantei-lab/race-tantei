import publicSite from "./public-site-entry-v10.js";
import type { Env } from "./v1/types.js";

function removeEmptyRunnerColumns(html:string):string{
  const css=`<style>
    .runner-table th:nth-child(7),
    .runner-table td:nth-child(7),
    .runner-table th:nth-child(8),
    .runner-table td:nth-child(8){display:none!important}
    .runner-table table{min-width:540px!important}
    @media(max-width:760px){
      .runner-table{overflow-x:auto!important}
      .runner-table table{min-width:520px!important}
      .runner-table th,.runner-table td{padding:8px 7px!important;font-size:12px!important}
    }
  </style>`;
  return html.replace("</head>",`${css}</head>`);
}

export default {
  async fetch(request:Request,env:Env,ctx:ExecutionContext):Promise<Response>{
    if(!publicSite.fetch)return new Response("NOT_FOUND",{status:404});
    const response=await publicSite.fetch(request,env,ctx);
    const path=new URL(request.url).pathname;
    if(!path.startsWith("/races/")||!response.ok||!response.headers.get("content-type")?.includes("text/html"))return response;
    try{
      const headers=new Headers(response.headers);headers.delete("content-length");
      return new Response(removeEmptyRunnerColumns(await response.text()),{status:response.status,headers});
    }catch{return response;}
  },
  async scheduled(controller:ScheduledController,env:Env,ctx:ExecutionContext):Promise<void>{
    if(publicSite.scheduled)await publicSite.scheduled(controller,env,ctx);
  }
} satisfies ExportedHandler<Env>;
