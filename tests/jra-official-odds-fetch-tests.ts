import { strict as assert } from "node:assert";
import { fetchFastJraOfficialOddsForRace } from "../src/v1/jra-official-odds-fetch.js";

const originalFetch = globalThis.fetch;
const target = { raceDate: "2026-08-09", venue: "中京", raceNo: 11 } as const;
const suffix = "S301202601061120260809Z/EA";
const cnames = {
  "単勝": `pw151ou${suffix}`,
  "馬連": `pw154ou${suffix}`,
  "ワイド": `pw155ou${suffix}`,
  "馬単": `pw156ou${suffix}`,
  "3連複": `pw157ou${suffix}`,
  "3連単": `pw158ou${suffix}`,
} as const;

const entryHtml = `<!doctype html><html><body>${Object.values(cnames).map((cname) =>
  `<a href="#" onclick="doAction('/JRADB/accessO.html','${cname}')">odds</a>`
).join("")}</body></html>`;

function pageFor(cname: string): string {
  const prefix = cname.slice(0, 7);
  const arity = prefix === "pw151ou" ? 1 : (prefix === "pw157ou" || prefix === "pw158ou") ? 3 : 2;
  const horses = Array.from({ length: arity }, (_, index) => `<td>${index + 1}</td>`).join("");
  const odds = arity === 1 ? "2.5" : arity === 2 ? "6.4" : "12.8";
  return `<!doctype html><html><body><h1>2026年8月9日 3回中京6日</h1><table><tr>${horses}<td>${odds}</td></tr></table></body></html>`;
}

let firstWinPost = true;
globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const url = String(input);
  if (url.includes("entry.test")) return new Response(entryHtml, { status: 200, headers: { "content-type": "text/html; charset=utf-8" } });
  if (!url.includes("/JRADB/accessO.html")) return new Response("not found", { status: 404 });
  const body = String(init?.body ?? "");
  const cname = new URLSearchParams(body).get("cname") ?? "";
  if (cname === cnames["単勝"] && firstWinPost) {
    firstWinPost = false;
    return new Response("not found", { status: 404 });
  }
  if (Object.values(cnames).includes(cname as never)) {
    return new Response(pageFor(cname), { status: 200, headers: { "content-type": "text/html; charset=utf-8" } });
  }
  return new Response("not found", { status: 404 });
};

try {
  const result = await fetchFastJraOfficialOddsForRace("https://entry.test/race", target);
  assert.equal(result.source, "jra-crawl-official");
  assert.ok(result.fallbackReason?.includes("JRA_ODDS_HTTP_404"));
  assert.equal(result.pages.length, 6);
  assert.deepEqual(new Set(result.pages.map((page) => page.betType)), new Set(["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"]));
  assert.equal(result.rows.length, 6);
  assert.ok(result.rows.every((row) => row.oddsMin > 1 && row.oddsMax >= row.oddsMin));
  console.log("JRA_OFFICIAL_ODDS_FETCH_OK", JSON.stringify({ source: result.source, fallbackReason: result.fallbackReason }));
} finally {
  globalThis.fetch = originalFetch;
}
