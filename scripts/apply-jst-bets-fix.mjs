import { readFileSync, writeFileSync } from "node:fs";

function replaceOnce(path, before, after) {
  const source = readFileSync(path, "utf8");
  if (source.includes(after)) return;
  if (!source.includes(before)) throw new Error(`Patch anchor not found: ${path}`);
  writeFileSync(path, source.replace(before, after));
}

replaceOnce(
  "src/v1/ui.ts",
  `  const dateLabel = (date: string): string => {
    const parsed = new Date(\`${"${date}"}T00:00:00+09:00\`);
    if (Number.isNaN(parsed.getTime())) return date;
    const day = ["日", "月", "火", "水", "木", "金", "土"][parsed.getDay()] ?? "";
    return \`${"${parsed.getMonth() + 1}"}月${"${parsed.getDate()}"}日（${"${day}"}）\`;
  };`,
  `  const dateLabel = (date: string): string => {
    const match = date.match(/^(\\d{4})-(\\d{2})-(\\d{2})$/);
    if (!match) return date;
    const year = Number(match[1]);
    const month = Number(match[2]);
    const dayOfMonth = Number(match[3]);
    const weekday = new Date(Date.UTC(year, month - 1, dayOfMonth)).getUTCDay();
    const day = ["日", "月", "火", "水", "木", "金", "土"][weekday] ?? "";
    return \`${"${month}"}月${"${dayOfMonth}"}日（${"${day}"}）\`;
  };`
);

replaceOnce(
  "src/complete.ts",
  `const DISCOVERY_REVISION = "2026-08-01-race-name-v1";`,
  `const DISCOVERY_REVISION = "2026-08-02-jst-bets-v3";`
);
replaceOnce(
  "src/complete.ts",
  `  if (minutesToStart <= 0 || minutesToStart > 240) return;`,
  `  if (minutesToStart <= 0) return;`
);
replaceOnce(
  "src/complete.ts",
  `  const status = minutesToStart <= 15 ? "locked" : "draft";
  if (status === "draft") prediction.bets = [];
  await savePrediction(env.DB, race.raceId, prediction, status);`,
  `  const status = minutesToStart <= 15 ? "locked" : "draft";
  await savePrediction(env.DB, race.raceId, prediction, status);`
);

console.log("Applied JST date and pre-race bet fix.");
