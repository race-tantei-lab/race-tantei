import { writeFile } from "node:fs/promises";
import { findCurrentEntryAnchor } from "./find-current-jra-entry-anchor.mjs";
import { syncCurrentWeekendCalendarDirect } from "./sync-current-weekend-calendar-direct.mjs";

globalThis.Bun = {
  write(path, data) {
    return writeFile(path, `${data}\n`, "utf8");
  }
};

// Entry discovery only needs the authoritative JRA meeting metadata. Do not
// rewrite rt_races before entry acquisition; race-day bootstrap separately
// repairs the calendar if it is actually incomplete.
const now = new Date();
const calendarReport = await syncCurrentWeekendCalendarDirect(now, { persist: false });
const discovery = await findCurrentEntryAnchor(now, calendarReport.meetings || []);
await writeFile("jra-entry-anchor-discovery.json", `${JSON.stringify({ ...discovery, calendarReport }, null, 2)}\n`, "utf8");

if (!Array.isArray(discovery.targetDates) || !discovery.targetDates.length) {
  console.log("JRA_NO_RACE_DAY_WITHIN_DISCOVERY_WINDOW");
  process.exit(0);
}
if (!Array.isArray(discovery.calendarMeetings) || !discovery.calendarMeetings.length) {
  throw new Error("JRA_RACE_DAY_MEETINGS_NOT_FOUND");
}
const requiredDates = Array.isArray(discovery.requiredProbeDates) ? discovery.requiredProbeDates : [];
if (!requiredDates.length) {
  console.log("JRA_NO_UPCOMING_ENTRY_SYNC_REQUIRED");
  process.exit(0);
}
if (!discovery.found) {
  throw new Error(`JRA_REQUIRED_ENTRY_ANCHOR_NOT_FOUND:${requiredDates.join(",")}`);
}

process.env.JRA_TARGET_RACE_DATES = requiredDates.join(",");
const anchors = Array.isArray(discovery.anchors) ? discovery.anchors.filter((anchor) => requiredDates.includes(anchor.targetDate)) : [];
const seeds = [...new Set(anchors.flatMap((anchor) => [anchor.anchorUrl, ...(anchor.discoveredLinks || [])]).filter(Boolean))];
if (!seeds.length) throw new Error("JRA_ENTRY_SEEDS_EMPTY");
process.env.JRA_SEED_ENTRY_URLS = seeds.join(",");

await import("./sync-upcoming-entries-direct.mjs");
