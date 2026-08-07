import { writeFile } from "node:fs/promises";
import { fetchJraPage, pageLooksLikeEntry, parseEntryPage } from "../dist-test/src/v1/jra.js";

const base = "https://www.jra.go.jp/JRADB/accessD.html?CNAME=";
const candidates = [
  ["old-correct", "pw01dde0101202601010120260725/FB"],
  ["old-wrong-00", "pw01dde0101202601010120260725/00"],
  ["old-no-suffix", "pw01dde0101202601010120260725"],
  ["current-sapporo-00", "pw01dde0101202601050120260808/00"],
  ["current-sapporo-fb", "pw01dde0101202601050120260808/FB"],
  ["current-sapporo-no-suffix", "pw01dde0101202601050120260808"],
  ["current-niigata-00", "pw01dde0104202602050120260808/00"],
  ["current-chukyo-00", "pw01dde0107202602050120260808/00"]
];

const rows = [];
for (const [label, cname] of candidates) {
  const url = `${base}${encodeURIComponent(cname)}`;
  try {
    const page = await fetchJraPage(url);
    let parsed = null;
    if (pageLooksLikeEntry(page.html)) {
      try {
        const bundle = parseEntryPage(page.html, page.url);
        parsed = {
          raceId: bundle.race.raceId,
          raceDate: bundle.race.raceDate,
          venue: bundle.race.venue,
          raceNo: bundle.race.raceNo,
          runners: bundle.runners.length
        };
      } catch (error) {
        parsed = { parseError: `${error?.name || "Error"}:${error?.message || String(error)}` };
      }
    }
    rows.push({ label, cname, status: page.status, finalUrl: page.url, entrySignature: pageLooksLikeEntry(page.html), parsed });
  } catch (error) {
    rows.push({ label, cname, error: `${error?.name || "Error"}:${error?.message || String(error)}` });
  }
}

const output = { generatedAtUtc: new Date().toISOString(), probes: rows };
await writeFile("jra-cname-suffix-probe.json", `${JSON.stringify(output, null, 2)}\n`, "utf8");
console.log(JSON.stringify(output, null, 2));
