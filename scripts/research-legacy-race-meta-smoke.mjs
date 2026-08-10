import process from "node:process";
import { fetchJraPage } from "../dist-test/src/v1/jra.js";
import { parseLegacyRaceMeta } from "./research-legacy-race-meta.mjs";

const CASES = [
  {
    url: "https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde1006201803060120180408%2F46",
    expect: { raceNo: 1, raceName: "サラ系3歳未勝利", distanceM: 1200, surface: "ダート", direction: "右" }
  },
  {
    url: "https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde1006201802010820180224%2F93",
    expect: { raceNo: 8, raceName: "サラ系4歳以上500万円以下", distanceM: 1200, surface: "ダート", direction: "右" }
  },
  {
    url: "https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde1006201701020720170107%2F21",
    expect: { raceNo: 7, raceName: "サラ系4歳以上1000万円以下", distanceM: 1200, surface: "ダート", direction: "右" }
  },
  {
    url: "https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde1004201802120620180902%2F47",
    expect: { raceNo: 6, raceName: "メイクデビュー新潟", distanceM: 1200, surface: "ダート", direction: "左" }
  },
  {
    url: "https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde1008202401010820240106%2FA8",
    expect: { raceNo: 8, raceName: "4歳以上2勝クラス", distanceM: 1200, surface: "ダート", direction: "右" }
  }
];

async function main() {
  const rows = [];
  for (const test of CASES) {
    const page = await fetchJraPage(test.url);
    const meta = parseLegacyRaceMeta(page.html, page.url);
    for (const [key, value] of Object.entries(test.expect)) {
      if (meta[key] !== value) throw new Error(`META_MISMATCH:${key}:expected=${value}:actual=${meta[key]}:${test.url}`);
    }
    if (!meta.conditions || meta.conditions.length < 3) throw new Error(`CONDITIONS_MISSING:${test.url}`);
    rows.push({ url: test.url, meta });
  }
  console.log(JSON.stringify({ ok: true, cases: rows.length, rows }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
