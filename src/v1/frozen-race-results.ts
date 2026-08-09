import { RESULTS_2024 } from "./frozen-results-2024.js";
import { RESULTS_2025 } from "./frozen-results-2025.js";
import { RESULTS_2026 } from "./frozen-results-2026.js";

const RESULTS:Record<string,string>={...RESULTS_2024,...RESULTS_2025,...RESULTS_2026};

export function frozenRaceOutcome(raceDate:string,venue:string,raceNo:number):"hit"|"miss"|null{
  const row=RESULTS[`${raceDate}|${venue}`];
  if(!row)return null;
  const [selected,hits=""]=row.split("|");
  if(!selected.split(".").includes(String(raceNo)))return null;
  return hits.split(".").filter(Boolean).includes(String(raceNo))?"hit":"miss";
}
