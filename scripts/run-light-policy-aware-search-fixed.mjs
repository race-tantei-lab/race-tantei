import { readFile, writeFile, unlink } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const sourcePath = new URL("./run-light-policy-aware-search.mjs", import.meta.url);
const temporaryPath = new URL("./.generated-run-light-policy-aware-search-fixed.mjs", import.meta.url);
let source = await readFile(sourcePath, "utf8");

const search = '    await writeFile("light-policy-aware-search.json", JSON.stringify(rejectedReport, null, 2) + "\\\\n");';
const replacement = '    await (await import("node:fs/promises")).writeFile("light-policy-aware-search.json", JSON.stringify(rejectedReport, null, 2) + "\\\\n");';

if (!source.includes(search)) {
  throw new Error("LIGHT_POLICY_REJECTION_WRITER_PATCH_MISSING");
}

source = source.replace(search, replacement);
await writeFile(temporaryPath, source, "utf8");
try {
  await import(`${pathToFileURL(temporaryPath.pathname).href}?v=${Date.now()}`);
} finally {
  await unlink(temporaryPath).catch(() => {});
}
