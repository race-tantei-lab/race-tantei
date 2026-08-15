import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { loadCompletedModelRuntime } from "../src/v1/completed-model-runtime";

type ParityFile = {
  modelVersion: string;
  modelSha256: string;
  featureNames: string[];
  vectors: Array<Array<number | null>>;
  expected: number[];
};

const dir = resolve(process.argv[2] ?? "worker-assets/_internal/completed-model");
const modelBytes = readFileSync(resolve(dir, "model.bin"));
const parity = JSON.parse(readFileSync(resolve(dir, "parity.json"), "utf8")) as ParityFile;
const buffer = modelBytes.buffer.slice(modelBytes.byteOffset, modelBytes.byteOffset + modelBytes.byteLength) as ArrayBuffer;
const runtime = loadCompletedModelRuntime(buffer);

if (parity.modelVersion !== "ten-year-completed-model") {
  throw new Error(`unexpected parity model version: ${parity.modelVersion}`);
}
if (runtime.featureCount !== parity.featureNames.length) {
  throw new Error(`feature count mismatch: runtime=${runtime.featureCount}, parity=${parity.featureNames.length}`);
}
if (parity.vectors.length !== parity.expected.length) {
  throw new Error(`parity row mismatch: vectors=${parity.vectors.length}, expected=${parity.expected.length}`);
}

let maxAbsError = 0;
let worstRow = -1;
for (let i = 0; i < parity.vectors.length; i += 1) {
  const features = parity.vectors[i].map((value) => value === null ? Number.NaN : value);
  const actual = runtime.predict(features);
  const expected = parity.expected[i];
  const error = Math.abs(actual - expected);
  if (error > maxAbsError) {
    maxAbsError = error;
    worstRow = i;
  }
}

const tolerance = 1e-11;
if (!Number.isFinite(maxAbsError) || maxAbsError > tolerance) {
  throw new Error(`WORKER_MODEL_PARITY_FAILED maxAbsError=${maxAbsError} worstRow=${worstRow} tolerance=${tolerance}`);
}

console.log(JSON.stringify({
  status: "WORKER_MODEL_PARITY_OK",
  modelVersion: parity.modelVersion,
  modelSha256: parity.modelSha256,
  featureCount: runtime.featureCount,
  treeCount: runtime.treeCount,
  nodeCount: runtime.nodeCount,
  rows: parity.vectors.length,
  maxAbsError,
  worstRow,
  tolerance,
}));
