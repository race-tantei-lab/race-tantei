import { writeFile } from "node:fs/promises";

globalThis.Bun = {
  write(path, data) {
    return writeFile(path, `${data}\n`, "utf8");
  }
};

await import("./sync-upcoming-entries-direct.mjs");
