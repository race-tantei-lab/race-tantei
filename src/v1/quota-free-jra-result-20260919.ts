import { fetchJraPage, pageLooksLikeResult, parseEntryPage, parseResultPage, toResultUrl } from "./jra.js";
import { parseJraPayoutsFromHtml } from "./jra-payout-fallback.js";
import { shell } from "./public-ui.js";

const ENTRY_URLS: Readonly<Record<string, string>> = {
  "2026-09-19-nakayama-01": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0106202604050120260919%2F5C",
  "2026-09-19-nakayama-02": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0106202604050220260919%2F11",
  "2026-09-19-nakayama-03": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0106202604050320260919%2FC6",
  "2026-09-19-nakayama-04": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0106202604050420260919%2F7B",
  "2026-09-19-nakayama-05": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0106202604050520260919%2F30",
  "2026-09-19-nakayama-06": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0106202604050620260919%2FE5",
  "2026-09-19-nakayama-07": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0106202604050720260919/9A",
  "2026-09-19-nakayama-08": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0106202604050820260919/4F",
  "2026-09-19-nakayama-09": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0106202604050920260919/04",
  "2026-09-19-nakayama-10": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0106202604051020260919/F9",
  "2026-09-19-nakayama-11": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0106202604051120260919%2FAE",
  "2026-09-19-nakayama-12": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0106202604051220260919/63",
  "2026-09-19-hanshin-01": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0109202604050120260919/3A",
  "2026-09-19-hanshin-02": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0109202604050220260919/EF",
  "2026-09-19-hanshin-03": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0109202604050320260919/A4",
  "2026-09-19-hanshin-04": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0109202604050420260919/59",
  "2026-09-19-hanshin-05": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0109202604050520260919/0E",
  "2026-09-19-hanshin-06": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0109202604050620260919/C3",
  "2026-09-19-hanshin-07": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0109202604050720260919/78",
  "2026-09-19-hanshin-08": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0109202604050820260919/2D",
  "2026-09-19-hanshin-09": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0109202604050920260919/E2",
  "2026-09-19-hanshin-10": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0109202604051020260919/D7",
  "2026-09-19-hanshin-11": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0109202604051120260919%2F8C",
  "2026-09-19-hanshin-12": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0109202604051220260919/41",
};

function esc(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch] ?? ch));
}

function canonicalCombination(betType: string, combination: string): string {
  const values = (String(combination).match(/\d{1,2}/g) ?? []).map(Number);
  if (["ワイド", "馬連", "3連複"].includes(betType)) values.sort((a, b) => a - b);
  return values.join("-");
}

export async function quotaFreeOfficialResultResponse(raceId: string): Promise<Response | null> {
  const entryUrl = ENTRY_URLS[raceId];
  if (!entryUrl) return null;

  // The two-character JRA CNAME suffix is page-specific. Replacing dde->sde
  // while keeping the entry-page suffix can point at a non-result page.
  // Read the official entry page first and use its embedded result link.
  let resultUrl = toResultUrl(entryUrl);
  const horseNames = new Map<number, string>();
  try {
    const entryPage = await fetchJraPage(entryUrl);
    const entry = parseEntryPage(entryPage.html, entryPage.url);
    if (entry.race.resultUrl) resultUrl = entry.race.resultUrl;
    for (const runner of entry.runners) horseNames.set(Number(runner.horseNo), String(runner.horseName || ""));
  } catch {
    // Keep the deterministic dde->sde fallback when the entry page itself is unavailable.
  }

  let resultPage;
  try {
    resultPage = await fetchJraPage(resultUrl);
  } catch {
    return null;
  }
  if (!pageLooksLikeResult(resultPage.html)) return null;

  let result;
  try {
    result = parseResultPage(resultPage.html, resultPage.url);
  } catch {
    return null;
  }
  if (result.race.raceId !== raceId || result.results.length < 2) return null;

  const payoutMap = new Map<string, typeof result.payouts[number]>();
  for (const payout of [...result.payouts, ...parseJraPayoutsFromHtml(resultPage.html)]) {
    const combination = canonicalCombination(payout.betType, payout.combination);
    payoutMap.set(`${payout.betType}:${combination}`, { ...payout, combination });
  }
  const payouts = [...payoutMap.values()];

  const rows = [...result.results]
    .sort((a, b) => Number(a.finishPosition ?? 999) - Number(b.finishPosition ?? 999) || Number(a.horseNo) - Number(b.horseNo))
    .map((row) => {
      const pos = row.finishPosition == null ? esc(row.resultStatus) : `${Number(row.finishPosition)}着`;
      const name = horseNames.get(Number(row.horseNo)) || "";
      return `<tr><td><b>${pos}</b></td><td>${Number(row.horseNo)}</td><td>${esc(name)}</td><td>${esc(row.timeText ?? "—")}</td><td>${esc(row.marginText ?? "—")}</td><td>${row.final3f == null ? "—" : Number(row.final3f).toFixed(1)}</td></tr>`;
    }).join("");

  const payoutRows = payouts
    .sort((a, b) => a.betType.localeCompare(b.betType, "ja") || a.combination.localeCompare(b.combination, "ja"))
    .map((row) => `<tr><td>${esc(row.betType)}</td><td><b>${esc(row.combination)}</b></td><td>${Number(row.payoutYen).toLocaleString("ja-JP")}円</td><td>${row.popularity == null ? "—" : `${Number(row.popularity)}番人気`}</td></tr>`)
    .join("");

  const race = result.race;
  const meta = [race.raceDate.replaceAll("-", "/"), race.venue, `${race.raceNo}R`, race.startTimeJst ? `${race.startTimeJst}発走` : null, race.surface, race.distanceM ? `${race.distanceM}m` : null]
    .filter(Boolean).join("　");
  const refundText = result.refundHorseNos.length ? `<p class="muted">返還馬番：${result.refundHorseNos.map(Number).join("、")}</p>` : "";

  const body = `
    <a class="back" href="/races/">← レース一覧へ</a>
    <section class="hero"><div class="race-title"><span class="race-no">${Number(race.raceNo)}R</span><h1>${esc(race.raceName || `${race.venue} ${race.raceNo}R`)}</h1><span class="status buy">JRA公式結果</span></div><p>${esc(meta)}</p></section>
    <section class="card panel"><h2>着順</h2><div class="runner-table"><table><thead><tr><th>着順</th><th>馬番</th><th>馬名</th><th>タイム</th><th>着差</th><th>上がり3F</th></tr></thead><tbody>${rows}</tbody></table></div></section>
    <section class="card panel"><h2>払戻</h2>${payoutRows ? `<div class="runner-table"><table><thead><tr><th>券種</th><th>組合せ</th><th>払戻</th><th>人気</th></tr></thead><tbody>${payoutRows}</tbody></table></div>` : '<p class="muted">JRA公式払戻を確認中です。</p>'}${refundText}</section>
    <p class="muted">D1障害時のJRA公式ページ直読表示です。買い目の精算・回収率はD1復旧後に自動反映します。</p>`;

  return new Response(shell(`${race.venue}${race.raceNo}R 結果`, body), {
    status: 200,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "public, max-age=45",
      "x-race-result-source": "jra-official-direct-quota-free-20260919",
    },
  });
}
