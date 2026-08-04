import { spawn } from "node:child_process";

const args = process.argv.slice(2);

function optionNumber(name, fallback) {
  const index = args.indexOf(name);
  if (index < 0 || !args[index + 1]) return fallback;
  const value = Number(args[index + 1]);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

const onceOnly = args.includes("--once");
const maxMinutes = optionNumber("--minutes", 360);
const port = optionNumber("--port", 8787);
const baseUrl = `http://127.0.0.1:${port}`;
const deadline = Date.now() + maxMinutes * 60_000;
const npxCommand = process.platform === "win32" ? "npx.cmd" : "npx";

if (!process.env.CLOUDFLARE_API_TOKEN) {
  console.error("CLOUDFLARE_API_TOKEN is not set in this terminal.");
  console.error('Run: export CLOUDFLARE_API_TOKEN="<your token with D1 Edit permission>"');
  process.exit(2);
}

let child;
let stopping = false;
let consecutiveFailures = 0;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchWithTimeout(url, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { signal: controller.signal, cache: "no-store" });
  } finally {
    clearTimeout(timer);
  }
}

async function readStatus() {
  const response = await fetchWithTimeout(`${baseUrl}/api/training/walk-forward/status`, 120_000);
  if (!response.ok) {
    throw new Error(`STATUS_HTTP_${response.status}:${await response.text()}`);
  }
  return response.json();
}

function progressLine(status, iteration) {
  const training = status?.training ?? {};
  const history = training.history ?? {};
  const calibration = status?.calibration ?? {};
  const imported = Number(history.importedUrls ?? 0);
  const totalUrls = Number(history.resultUrls ?? 0);
  const stored = Number(history.storedRaces ?? 0);
  const failures = Number(history.failedUrls ?? 0);
  const permanent = Number(history.permanentFailures ?? 0);
  const generated = Number(training.generatedRaces ?? 0);
  const target = Number(training.targetRaces ?? 0);
  const phase = String(training.phase ?? "unknown");
  const calibrationPhase = String(calibration.phase ?? "waiting");
  const scored = Number(calibration.scoredRaces ?? 0);
  const applied = Number(calibration.appliedRaces ?? 0);
  return [
    `iteration=${iteration}`,
    `phase=${phase}`,
    `history=${imported}/${totalUrls}`,
    `stored=${stored}`,
    `failures=${failures}`,
    `permanent=${permanent}`,
    `features=${generated}/${target}`,
    `calibration=${calibrationPhase}`,
    `scored=${scored}`,
    `applied=${applied}`
  ].join(" ");
}

function pipelineComplete(status) {
  const trainingComplete = status?.training?.complete === true;
  const calibrationPhase = status?.calibration?.phase;
  return trainingComplete && (calibrationPhase === "complete" || calibrationPhase === "failed");
}

async function waitUntilReady() {
  for (let attempt = 1; attempt <= 90; attempt += 1) {
    if (child.exitCode !== null) {
      throw new Error(`WRANGLER_EXITED_${child.exitCode}`);
    }
    try {
      const status = await readStatus();
      console.log(`Local Worker ready: ${progressLine(status, 0)}`);
      return status;
    } catch (error) {
      if (attempt === 90) throw error;
      await sleep(1_000);
    }
  }
  throw new Error("LOCAL_WORKER_NOT_READY");
}

async function runScheduledIteration(iteration) {
  const cron = encodeURIComponent("* * * * *");
  const response = await fetchWithTimeout(`${baseUrl}/__scheduled?cron=${cron}`, 180_000);
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`SCHEDULED_HTTP_${response.status}:${text}`);
  }
  const status = await readStatus();
  console.log(progressLine(status, iteration));
  return status;
}

async function stopChild() {
  if (!child || child.exitCode !== null) return;
  child.kill("SIGTERM");
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    sleep(5_000)
  ]);
  if (child.exitCode === null) child.kill("SIGKILL");
}

async function shutdown(signal) {
  if (stopping) return;
  stopping = true;
  console.log(`Received ${signal}; stopping after the last committed checkpoint.`);
  await stopChild();
  process.exit(0);
}

process.on("SIGINT", () => void shutdown("SIGINT"));
process.on("SIGTERM", () => void shutdown("SIGTERM"));

child = spawn(
  npxCommand,
  [
    "wrangler",
    "dev",
    "--config",
    "wrangler.learning.jsonc",
    "--test-scheduled",
    "--port",
    String(port),
    "--log-level",
    "warn"
  ],
  {
    cwd: process.cwd(),
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"]
  }
);

child.stdout.on("data", (chunk) => process.stdout.write(`[wrangler] ${chunk}`));
child.stderr.on("data", (chunk) => process.stderr.write(`[wrangler] ${chunk}`));

try {
  const initialStatus = await waitUntilReady();
  if (pipelineComplete(initialStatus)) {
    console.log("Walk-forward pipeline is already complete.");
  } else {
    let iteration = 0;
    while (!stopping && Date.now() < deadline) {
      iteration += 1;
      try {
        const status = await runScheduledIteration(iteration);
        consecutiveFailures = 0;
        if (pipelineComplete(status)) {
          console.log("Walk-forward pipeline completed.");
          break;
        }
        if (onceOnly) break;
        await sleep(1_000);
      } catch (error) {
        consecutiveFailures += 1;
        console.error(`Iteration ${iteration} failed (${consecutiveFailures}/10):`, error);
        if (onceOnly || consecutiveFailures >= 10) throw error;
        await sleep(Math.min(30_000, 2_000 * consecutiveFailures));
      }
    }
    if (!stopping && Date.now() >= deadline) {
      console.log(`Stopped after ${maxMinutes} minutes. Run the same command again to resume.`);
    }
  }
} catch (error) {
  console.error("Local walk-forward runner failed:", error);
  process.exitCode = 1;
} finally {
  await stopChild();
}
