import { writeFile } from "node:fs/promises";
import { findCurrentEntryAnchor } from "./find-current-jra-entry-anchor.mjs";

globalThis.Bun = {
  write(path, data) {
    return writeFile(path, `${data}\n`, "utf8");
  }
};

const discovery = await findCurrentEntryAnchor();
await writeFile("jra-entry-anchor-discovery.json", `${JSON.stringify(discovery, null, 2)}\n`, "utf8");
if (!discovery.found) {
  throw new Error(`JRA_CURRENT_WEEKEND_ANCHORS_INCOMPLETE:${JSON.stringify({ targetDates: discovery.targetDates, anchors: discovery.anchors?.map((a) => a.targetDate) || [] })}`);
}

const anchors = Array.isArray(discovery.anchors) && discovery.anchors.length ? discovery.anchors : [discovery];
const seeds = [...new Set(anchors.flatMap((anchor) => [anchor.anchorUrl, ...(anchor.discoveredLinks || [])]).filter(Boolean))];
if (!seeds.length) throw new Error("JRA_CURRENT_ENTRY_SEEDS_EMPTY");
process.env.JRA_SEED_ENTRY_URLS = seeds.join(",");
await import("./sync-upcoming-entries-direct.mjs");
