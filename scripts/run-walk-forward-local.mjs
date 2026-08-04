const args = process.argv.slice(2);

function optionNumber(name, fallback) {
  const index = args.indexOf(name);
  if (index < 0 || !args[index + 1]) return fallback;
  const value = Number(args[index + 1]);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

const onceOnly = args.includes("--once");
const maxMinutes = optionNumber("--minutes", 360);
const deadline = Date.now() + maxMinutes * 60_000;
const accountId = process.env.CLOUDFLARE_ACCOUNT_ID || "3c6d1826b573b2e68cb13ec37e9e8ade";
const databaseId = process.env.CLOUDFLARE_D1_DATABASE_ID || "949b5e8b-d1a4-4c4e-80d1-d031afdc03de";
const apiToken = process.env.CLOUDFLARE_API_TOKEN;
const apiUrl = `https://api.cloudflare.com/client/v4/accounts/${accountId}/d1/database/${databaseId}/query`;

if (!apiToken) {
  console.error("CLOUDFLARE_API_TOKEN is not set in this terminal.");
  console.error('Run: export CLOUDFLARE_API_TOKEN="<your D1 token>"');
  process.exit(2);
}

let stopping = false;
let consecutiveFailures = 0;
let requestChain = Promise.resolve();

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function normalizeParam(value) {
  if (value === undefined) return null;
  if (typeof value === "boolean") return value ? 1 : 0;
  if (typeof value === "bigint") return Number(value);
  if (value instanceof Date) return value.toISOString();
  if (value instanceof Uint8Array) return Array.from(value);
  return value;
}

function errorText(payload, status) {
  const messages = Array.isArray(payload?.errors)
    ? payload.errors.map((row) => `${row?.code ?? "?"}:${row?.message ?? "unknown"}`).join(" | ")
    : "";
  return `D1_HTTP_${status}${messages ? `:${messages}` : ""}`;
}

async function performApiQuery(queries) {
  const body = queries.length === 1 ? queries[0] : { batch: queries };
  let lastError;

  for (let attempt = 1; attempt <= 6; attempt += 1) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 120_000);
    try {
      const response = await fetch(apiUrl, {
        method: "POST",
        signal: controller.signal,
        headers: {
          Authorization: `Bearer ${apiToken}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(body)
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok || payload?.success !== true) {
        const error = new Error(errorText(payload, response.status));
        if (response.status === 429 || response.status >= 500) {
          lastError = error;
          await sleep(Math.min(30_000, attempt * 2_000));
          continue;
        }
        throw error;
      }

      const results = Array.isArray(payload.result) ? payload.result : [];
      const failed = results.find((row) => row?.success === false);
      if (failed) throw new Error(`D1_QUERY_FAILED:${JSON.stringify(failed)}`);
      return results;
    } catch (error) {
      if (error?.name === "AbortError" || error instanceof TypeError) {
        lastError = error;
        await sleep(Math.min(30_000, attempt * 2_000));
        continue;
      }
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  throw lastError ?? new Error("D1_API_RETRY_EXHAUSTED");
}

function enqueueApiQuery(queries) {
  const task = requestChain.then(async () => {
    const result = await performApiQuery(queries);
    await sleep(80);
    return result;
  });
  requestChain = task.catch(() => undefined);
  return task;
}

class RestD1PreparedStatement {
  constructor(database, sql, params = []) {
    this.database = database;
    this.sql = sql;
    this.params = params;
  }

  bind(...values) {
    return new RestD1PreparedStatement(this.database, this.sql, values.map(normalizeParam));
  }

  queryObject() {
    return { sql: this.sql, params: this.params };
  }

  async all() {
    const [result] = await this.database.queryMany([this.queryObject()]);
    return {
      results: Array.isArray(result?.results) ? result.results : [],
      success: result?.success !== false,
      meta: result?.meta ?? {}
    };
  }

  async first(columnName) {
    const result = await this.all();
    const row = result.results[0];
    if (row === undefined) return null;
    if (columnName) return row?.[columnName] ?? null;
    return row;
  }

  async run() {
    const [result] = await this.database.queryMany([this.queryObject()]);
    return {
      results: Array.isArray(result?.results) ? result.results : [],
      success: result?.success !== false,
      meta: result?.meta ?? {}
    };
  }

  async raw() {
    const result = await this.all();
    return result.results.map((row) => Object.values(row));
  }
}

class RestD1Database {
  prepare(sql) {
    return new RestD1PreparedStatement(this, sql);
  }

  async queryMany(queries) {
    return enqueueApiQuery(queries);
  }

  async batch(statements) {
    const queries = statements.map((statement) => {
      if (!(statement instanceof RestD1PreparedStatement)) {
        throw new Error("D1_BATCH_REQUIRES_PREPARED_STATEMENTS");
      }
      return statement.queryObject();
    });
    const results = await this.queryMany(queries);
    return results.map((result) => ({
      results: Array.isArray(result?.results) ? result.results : [],
      success: result?.success !== false,
      meta: result?.meta ?? {}
    }));
  }

  async exec(sql) {
    const results = await this.queryMany([{ sql, params: [] }]);
    return {
      count: results.length,
      duration: results.reduce((sum, row) => sum + Number(row?.meta?.duration ?? 0), 0)
    };
  }
}

const db = new RestD1Database();
const CRON_ATTEMPT_KEY = "walk_forward_cron:last_attempt";
const CRON_HEARTBEAT_KEY = "walk_forward_cron:last_success";
const CRON_ERROR_KEY = "walk_forward_cron:last_error";
const CRON_DURATION_KEY = "walk_forward_cron:last_duration_ms";
const CRON_STAGE_KEY = "walk_forward_cron:last_stage";
const CRON_DELTA_KEY = "walk_forward_cron:last_delta";

function progressLine(status, iteration) {
  const training = status?.training ?? {};
  const history = training.history ?? {};
  const calibration = status?.calibration ?? {};
  return [
    `iteration=${iteration}`,
    `phase=${String(training.phase ?? "unknown")}`,
    `history=${Number(history.importedUrls ?? 0)}/${Number(history.resultUrls ?? 0)}`,
    `stored=${Number(history.storedRaces ?? 0)}`,
    `failures=${Number(history.failedUrls ?? 0)}`,
    `permanent=${Number(history.permanentFailures ?? 0)}`,
    `features=${Number(training.generatedRaces ?? 0)}/${Number(training.targetRaces ?? 0)}`,
    `calibration=${String(calibration.phase ?? "waiting")}`,
    `scored=${Number(calibration.scoredRaces ?? 0)}`,
    `applied=${Number(calibration.appliedRaces ?? 0)}`
  ].join(" ");
}

function pipelineComplete(status) {
  const trainingComplete = status?.training?.complete === true;
  const calibrationPhase = status?.calibration?.phase;
  return trainingComplete && (calibrationPhase === "complete" || calibrationPhase === "failed");
}

function deltaText(status) {
  const training = status?.training ?? {};
  const history = training.history ?? {};
  const calibration = status?.calibration ?? {};
  return `履歴 ${Number(history.importedUrls ?? 0)}/${Number(history.resultUrls ?? 0)}・保存${Number(history.storedRaces ?? 0)}R・基礎予想 ${Number(training.generatedRaces ?? 0)}/${Number(training.targetRaces ?? 0)}・再予想${Number(calibration.appliedRaces ?? 0)}R`;
}

async function main() {
  const [trainingModule, calibrationModule, stateModule] = await Promise.all([
    import("../dist-test/src/v1/walk-forward-training.js"),
    import("../dist-test/src/v1/worker-calibration-v2.js"),
    import("../dist-test/src/v1/history-batch-db.js")
  ]);
  const {
    getWalkForwardTrainingProgress,
    runWalkForwardTrainingStep
  } = trainingModule;
  const {
    getWorkerCalibrationState,
    runWorkerCalibrationStep
  } = calibrationModule;
  const { setHistoryStatesBatch } = stateModule;

  async function readStatus() {
    const [training, calibration] = await Promise.all([
      getWalkForwardTrainingProgress(db),
      getWorkerCalibrationState(db)
    ]);
    return { training, calibration };
  }

  async function record(values) {
    await setHistoryStatesBatch(db, values);
  }

  async function runIteration(iteration) {
    const startedAt = Date.now();
    await record([
      { key: CRON_ATTEMPT_KEY, value: new Date(startedAt).toISOString() },
      { key: CRON_ERROR_KEY, value: "" }
    ]);

    let stage = "history";
    try {
      const before = await readStatus();
      if (!before.training.complete) {
        const result = await runWalkForwardTrainingStep(db, 12);
        stage = typeof result?.stage === "string" ? result.stage : before.training.phase;
      } else if (before.calibration.phase !== "complete" && before.calibration.phase !== "failed") {
        await runWorkerCalibrationStep(db);
        stage = "calibration";
      } else {
        stage = before.calibration.phase;
      }

      const after = await readStatus();
      await record([
        { key: CRON_HEARTBEAT_KEY, value: new Date().toISOString() },
        { key: CRON_DURATION_KEY, value: String(Date.now() - startedAt) },
        { key: CRON_STAGE_KEY, value: stage },
        { key: CRON_DELTA_KEY, value: deltaText(after) },
        { key: CRON_ERROR_KEY, value: "" }
      ]);
      console.log(progressLine(after, iteration));
      return after;
    } catch (error) {
      const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
      await record([
        { key: CRON_DURATION_KEY, value: String(Date.now() - startedAt) },
        { key: CRON_STAGE_KEY, value: stage },
        { key: CRON_DELTA_KEY, value: "Mac処理失敗（自動再試行）" },
        { key: CRON_ERROR_KEY, value: message.slice(0, 500) }
      ]).catch(() => undefined);
      throw error;
    }
  }

  const probe = await db.prepare("SELECT 1 AS ok").first();
  if (Number(probe?.ok ?? 0) !== 1) throw new Error("D1_CONNECTION_CHECK_FAILED");

  const initialStatus = await readStatus();
  console.log(`D1 connection ready: ${progressLine(initialStatus, 0)}`);
  if (pipelineComplete(initialStatus)) {
    console.log("Walk-forward pipeline is already complete.");
    return;
  }

  let iteration = 0;
  while (!stopping && Date.now() < deadline) {
    iteration += 1;
    try {
      const status = await runIteration(iteration);
      consecutiveFailures = 0;
      if (pipelineComplete(status)) {
        console.log("Walk-forward pipeline completed.");
        return;
      }
      if (onceOnly) return;
      await sleep(2_000);
    } catch (error) {
      consecutiveFailures += 1;
      console.error(`Iteration ${iteration} failed (${consecutiveFailures}/10):`, error);
      if (onceOnly || consecutiveFailures >= 10) throw error;
      await sleep(Math.min(60_000, 5_000 * consecutiveFailures));
    }
  }

  if (!stopping && Date.now() >= deadline) {
    console.log(`Stopped after ${maxMinutes} minutes. Run the same command again to resume.`);
  }
}

process.on("SIGINT", () => {
  stopping = true;
  console.log("Control+C received. The runner will stop after the current D1 request.");
});
process.on("SIGTERM", () => {
  stopping = true;
});

main().catch((error) => {
  console.error("Local walk-forward runner failed:", error);
  process.exitCode = 1;
});
