import { writeFile } from "node:fs/promises";
import { findCurrentEntryAnchor } from "./find-current-jra-entry-anchor.mjs";

globalThis.Bun = {
  write(path, data) {
    return writeFile(path, `${data}\n`, "utf8");
  }
};

const discovery = await findCurrentEntryAnchor();
await writeFile("jra-entry-anchor-discovery.json", `${JSON.stringify(discovery, null, 2)}\n`, "utf8");

if (!Array.isArray(discovery.targetDates) || !discovery.targetDates.length) {
  throw new Error("JRA_CURRENT_WEEKEND_DATES_NOT_FOUND");
}
if (!Array.isArray(discovery.calendarMeetings) || !discovery.calendarMeetings.length) {
  throw new Error("JRA_CURRENT_WEEKEND_MEETINGS_NOT_FOUND");
}

process.env.JRA_TARGET_RACE_DATES = discovery.targetDates.join(",");
const anchors = Array.isArray(discovery.anchors) ? discovery.anchors : [];
const seeds = [...new Set(anchors.flatMap((anchor) => [anchor.anchorUrl, ...(anchor.discoveredLinks || [])]).filter(Boolean))];
process.env.JRA_SEED_ENTRY_URLS = seeds.join(",");

await import("./sync-upcoming-entries-direct.mjs");
