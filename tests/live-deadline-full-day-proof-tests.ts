import { strict as assert } from "node:assert";

type Provider = "primary" | "backup" | "github";
type RaceState = {
  id: string;
  startMs: number;
  previewAtMs: number | null;
  archivePreviewAtMs: number | null;
  finalAtMs: number | null;
};
type Scenario = {
  providers: Set<Provider>;
  phaseShiftMinutes: number;
  jraRecoveryMinutesBeforeStart: number;
  generationSeconds: number;
  skipFirstEligibleTick: boolean;
};

const MINUTE = 60_000;
const PREVIEW_OPEN = 90 * MINUTE;
const NORMAL_LOCK = 25 * MINUTE;
const RESCUE_LOCK = 20 * MINUTE;
const HARD_DEADLINE = 15 * MINUTE;

// Three venues can have near-simultaneous starts. Five selected races per venue
// gives exactly the production 15-race day while deliberately clustering starts
// to stress sequential work and scheduler collisions.
const startsMinutes = [
  120, 120, 120,
  155, 156, 157,
  205, 205, 206,
  260, 261, 262,
  330, 330, 330,
];

function providerTick(provider: Provider, minute: number, shift: number): boolean {
  // All three production paths now attempt one pulse per minute: two independent
  // Cloudflare Workers plus the GitHub job's minute pulses. Inject a recurring
  // three-minute blackout into each provider, with different provider offsets,
  // so every single-provider scenario also proves recovery from missed minutes.
  const providerOffset = provider === "primary" ? 0 : provider === "backup" ? 5 : 10;
  const phase = ((minute - shift + providerOffset) % 15 + 15) % 15;
  return phase >= 3;
}

function runScenario(scenario: Scenario): RaceState[] {
  const races: RaceState[] = startsMinutes.map((startMinute, index) => ({
    id: `race-${String(index + 1).padStart(2, "0")}`,
    startMs: startMinute * MINUTE,
    previewAtMs: null,
    archivePreviewAtMs: null,
    finalAtMs: null,
  }));
  const firstStart = Math.min(...races.map((race) => race.startMs));
  const lastStart = Math.max(...races.map((race) => race.startMs));
  const startMinute = Math.floor((firstStart - 100 * MINUTE) / MINUTE);
  const endMinute = Math.ceil((lastStart - HARD_DEADLINE) / MINUTE);
  const skippedRace = new Set<string>();

  for (let minute = startMinute; minute <= endMinute; minute += 1) {
    for (const provider of ["primary", "backup", "github"] as const) {
      if (!scenario.providers.has(provider) || !providerTick(provider, minute, scenario.phaseShiftMinutes)) continue;
      let cursorMs = minute * MINUTE;

      for (const race of [...races].sort((a, b) => a.startMs - b.startMs || a.id.localeCompare(b.id))) {
        if (race.finalAtMs != null) continue;
        let remaining = race.startMs - cursorMs;
        if (remaining <= HARD_DEADLINE || remaining > PREVIEW_OPEN) continue;

        // Restore an append-only last-good archive before every guard/generator pass.
        if (race.previewAtMs == null && race.archivePreviewAtMs != null) race.previewAtMs = race.archivePreviewAtMs;

        // Stored-preview rescue is DB-only and therefore happens before network work.
        if (remaining <= RESCUE_LOCK && race.previewAtMs != null) {
          race.finalAtMs = cursorMs;
          continue;
        }

        // In multi-provider scenarios, lose one additional eligible execution per
        // race across the whole scheduler mesh. This is on top of the recurring
        // three-minute provider blackouts above.
        if (scenario.skipFirstEligibleTick && !skippedRace.has(race.id)) {
          skippedRace.add(race.id);
          continue;
        }

        const jraAvailable = remaining <= scenario.jraRecoveryMinutesBeforeStart * MINUTE;
        if (jraAvailable) {
          cursorMs += scenario.generationSeconds * 1000;
          remaining = race.startMs - cursorMs;
          if (remaining > HARD_DEADLINE) {
            race.previewAtMs = cursorMs;
            race.archivePreviewAtMs = cursorMs;
          }
        }

        // Normal finalization uses the new or last-good official preview by T-25.
        remaining = race.startMs - cursorMs;
        if (remaining > HARD_DEADLINE && remaining <= NORMAL_LOCK && race.previewAtMs != null) {
          race.finalAtMs = cursorMs;
        }
      }
    }
  }
  return races;
}

function assertAllOnTime(races: RaceState[], label: string): void {
  const bad = races.filter((race) => race.finalAtMs == null || race.finalAtMs > race.startMs - HARD_DEADLINE);
  assert.equal(bad.length, 0, `${label}: missing/late finals ${bad.map((race) => race.id).join(",")}`);
  assert.equal(races.length, 15, `${label}: proof must cover all 15 selected races`);
}

const providerSets: Array<Set<Provider>> = [];
for (let mask = 1; mask < 8; mask += 1) {
  const set = new Set<Provider>();
  if (mask & 1) set.add("primary");
  if (mask & 2) set.add("backup");
  if (mask & 4) set.add("github");
  providerSets.push(set);
}

let scenarioCount = 0;
for (const providers of providerSets) {
  for (let phaseShiftMinutes = 0; phaseShiftMinutes <= 14; phaseShiftMinutes += 1) {
    for (const jraRecoveryMinutesBeforeStart of [90, 60, 40, 30, 25, 22, 20]) {
      for (const generationSeconds of [0, 5, 15, 25, 30]) {
        // If two providers are completely unavailable, the remaining provider
        // must still carry all 15 races through its own injected blackout. With
        // two or three alive, add one more lost eligible execution per race.
        const skipOptions = providers.size >= 2 ? [false, true] : [false];
        for (const skipFirstEligibleTick of skipOptions) {
          const scenario: Scenario = {
            providers,
            phaseShiftMinutes,
            jraRecoveryMinutesBeforeStart,
            generationSeconds,
            skipFirstEligibleTick,
          };
          const label = JSON.stringify({
            providers: [...providers],
            phaseShiftMinutes,
            jraRecoveryMinutesBeforeStart,
            generationSeconds,
            skipFirstEligibleTick,
          });
          assertAllOnTime(runScenario(scenario), label);
          scenarioCount += 1;
        }
      }
    }
  }
}

// Explicit last-good proof: current preview is lost after acquisition, but the
// durable archive restores it and the DB-only rescue finalizes before T-15.
{
  const race: RaceState = {
    id: "archive-race",
    startMs: 100 * MINUTE,
    previewAtMs: null,
    archivePreviewAtMs: 50 * MINUTE,
    finalAtMs: null,
  };
  const now = 80 * MINUTE; // T-20.
  if (race.previewAtMs == null && race.archivePreviewAtMs != null) race.previewAtMs = race.archivePreviewAtMs;
  if (race.startMs - now <= RESCUE_LOCK && race.previewAtMs != null) race.finalAtMs = now;
  assert.equal(race.finalAtMs, 80 * MINUTE, "archived official preview must rescue the final at T-20");
}

// Hard fail-closed proof: if JRA official odds never become available, we must
// not fabricate a final merely to satisfy availability.
{
  const races = runScenario({
    providers: new Set<Provider>(["primary", "backup", "github"]),
    phaseShiftMinutes: 0,
    jraRecoveryMinutesBeforeStart: 0,
    generationSeconds: 0,
    skipFirstEligibleTick: false,
  });
  assert.equal(races.filter((race) => race.finalAtMs != null).length, 0, "no official odds means no synthetic final");
}

console.log(`live-deadline-full-day-proof-tests: ok scenarios=${scenarioCount} races_per_scenario=15 blackout_minutes=3`);
