import { writeFile } from "node:fs/promises";
import { syncCurrentWeekendCalendarDirect } from "./sync-current-weekend-calendar-direct.mjs";

globalThis.Bun = {
  write(path, data) {
    return writeFile(path, `${data}\n`, "utf8");
  }
};

const report = await syncCurrentWeekendCalendarDirect();
console.log("WEEKEND_CALENDAR_SYNC_OK");
console.log(JSON.stringify(report, null, 2));
