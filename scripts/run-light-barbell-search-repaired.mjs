import { readFile, writeFile, unlink } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const sourcePath = new URL("./run-light-barbell-search.mjs", import.meta.url);
const generatedPath = new URL("./.generated-run-light-barbell-search-repaired.mjs", import.meta.url);
let source = await readFile(sourcePath, "utf8");

const marker = 'await writeFile(generatedPath, source, "utf8");';
if (!source.includes(marker)) {
  throw new Error("LIGHT_BARBELL_REPAIR_MARKER_MISSING");
}

const repair = [
  'while (source.includes("\\\\`")) source = source.replaceAll("\\\\`", "`");',
  'while (source.includes("\\\\${")) source = source.replaceAll("\\\\${", "${");',
  marker
].join("\n");

source = source.replace(marker, repair);
await writeFile(generatedPath, source, "utf8");

try {
  await import(`${pathToFileURL(generatedPath.pathname).href}?v=${Date.now()}`);
} finally {
  await unlink(generatedPath).catch(() => {});
}
