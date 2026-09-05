import { readFile, writeFile } from "node:fs/promises";
import { findCurrentEntryAnchor } from "./find-current-jra-entry-anchor.mjs";
import { syncCurrentWeekendCalendarDirect } from "./sync-current-weekend-calendar-direct.mjs";

globalThis.Bun = {
  write(path, data) {
    return writeFile(path, `${data}\n`, "utf8");
  }
};

async function meetingReport(now) {
  const path = process.env.JRA_MEETING_DISCOVERY_FILE || "";
  if (path) {
    try {
      const parsed = JSON.parse(await readFile(path, "utf8"));
      const meetings = Array.isArray(parsed.meetings) ? parsed.meetings : [];
      const dates = [...new Set(meetings.map((row) => String(row?.date || "")).filter(Boolean))].sort();
      if (meetings.length && dates.length) {
        console.log("JRA_MEETINGS_FROM_D1_EXPORT", JSON.stringify({ dates, meetings: meetings.length }));
        return { generatedAtUtc: new Date().toISOString(), dates, meetings, source: "d1-export", persisted: false };
      }
    } catch (error) {
      console.warn("JRA_MEETING_DISCOVERY_FILE_FAILED", error instanceof Error ? error.message : String(error));
    }
  }

  // Fallback only. GitHub-hosted runners may be blocked by JRA calendar pages,
  // so scheduled production sync supplies meeting metadata from a D1 export.
  return syncCurrentWeekendCalendarDirect(now, { persist: false });
}

const now = new Date();
const calendarReport = await meetingReport(now);
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

// Saving remains a separate step so a JRA fetch success is not hidden by a D1 quota failure.
await import("./sync-upcoming-entries-direct.mjs");
