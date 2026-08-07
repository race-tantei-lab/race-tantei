import { writeFile } from "node:fs/promises";
import { findCurrentEntryAnchor } from "./find-current-jra-entry-anchor.mjs";

globalThis.Bun = {
  write(path, data) {
    return writeFile(path, `${data}\n`, "utf8");
  }
};

const anchor = await findCurrentEntryAnchor();
await writeFile("jra-entry-anchor-discovery.json", `${JSON.stringify(anchor, null, 2)}\n`, "utf8");
if (!anchor.found) {
  throw new Error("JRA_CURRENT_ENTRY_ANCHOR_NOT_FOUND");
}

process.env.JRA_SEED_ENTRY_URLS = [anchor.anchorUrl, ...anchor.discoveredLinks]
  .filter(Boolean)
  .join(",");
await import("./sync-upcoming-entries-direct.mjs");
