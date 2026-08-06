import app from "./production-ui-entry.js";
import type { Env } from "./v1/types.js";

const PRODUCTION_START_DATE = "2026-08-01";
const PRODUCTION_START_LABEL = "2026年8月1日";

function rewriteProductionHtml(source: string): string {
  return source
    .replaceAll("検証結果を含めず、公開後の実績だけ", `${PRODUCTION_START_LABEL}以降・検証結果を除外`)
    .replaceAll("本番成績はゼロから集計", "本番成績は2026年8月から集計")
    .replaceAll(
      "ここには新モデルで発走前に公開・固定した買い目だけを積み上げます。",
      `${PRODUCTION_START_LABEL}以降に、新モデルで発走前に公開・固定した買い目だけを積み上げます。`
    )
    .replaceAll(
      "購入額・払戻額は本番公開後の精算済み買い目のみです。",
      `購入額・払戻額は${PRODUCTION_START_LABEL}以降の精算済み本番買い目のみです。`
    )
    .replaceAll("本番公開後のみ", "2026年8月以降")
    .replaceAll(
      "発走前に公開・固定した買い目だけを集計します。",
      `${PRODUCTION_START_LABEL}以降、発走前に公開・固定した買い目だけを集計します。`
    )
    .replaceAll("本番レースの精算後に自動で追加されます。", "2026年8月の本番レースが精算されると自動で追加されます。")
    .replaceAll("新モデルの本番精算はまだありません", "2026年8月の本番精算はまだありません")
    .replaceAll("集計開始待ち", "8月集計開始待ち");
}

async function rewriteResponse(response: Response, pathname: string): Promise<Response> {
  const contentType = response.headers.get("content-type") ?? "";

  if (contentType.includes("application/json") && pathname.startsWith("/api/performance/courses")) {
    const payload = await response.json<Record<string, unknown>>();
    const headers = new Headers(response.headers);
    headers.set("cache-control", "no-store, max-age=0");
    return new Response(JSON.stringify({ ...payload, startDate: PRODUCTION_START_DATE }, null, 2), {
      status: response.status,
      statusText: response.statusText,
      headers
    });
  }

  if (!contentType.includes("text/html") || (pathname !== "/" && pathname !== "/performance")) {
    return response;
  }

  const body = rewriteProductionHtml(await response.text());
  const headers = new Headers(response.headers);
  headers.set("cache-control", "no-store, max-age=0");
  headers.set("content-length", String(new TextEncoder().encode(body).length));
  headers.set("x-race-ui-version", "production-august-start-v1");
  return new Response(body, {
    status: response.status,
    statusText: response.statusText,
    headers
  });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (!app.fetch) return new Response("NOT_FOUND", { status: 404 });
    const pathname = new URL(request.url).pathname;
    return rewriteResponse(await app.fetch(request, env, ctx), pathname);
  },

  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (app.scheduled) await app.scheduled(controller, env, ctx);
  }
} satisfies ExportedHandler<Env>;
