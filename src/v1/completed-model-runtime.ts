const MAGIC = "RTLMOD01";
const VERSION = 1;
const HEADER_BYTES = 40;
const NODE_BYTES = 24;

export interface CompletedModelRuntime {
  readonly featureCount: number;
  readonly treeCount: number;
  readonly nodeCount: number;
  predict(features: readonly number[]): number;
}

function readMagic(bytes: Uint8Array): string {
  let out = "";
  for (let i = 0; i < 8; i += 1) out += String.fromCharCode(bytes[i] ?? 0);
  return out;
}

function sigmoid(value: number, scale: number): number {
  const z = scale * value;
  if (z >= 0) {
    const e = Math.exp(-z);
    return 1 / (1 + e);
  }
  const e = Math.exp(z);
  return e / (1 + e);
}

export function loadCompletedModelRuntime(buffer: ArrayBuffer): CompletedModelRuntime {
  const bytes = new Uint8Array(buffer);
  if (bytes.byteLength < HEADER_BYTES) throw new Error("completed model asset is truncated");
  if (readMagic(bytes) !== MAGIC) throw new Error("completed model asset magic mismatch");

  const view = new DataView(buffer);
  const version = view.getUint32(8, true);
  if (version !== VERSION) throw new Error(`unsupported completed model asset version: ${version}`);

  const featureCount = view.getUint32(12, true);
  const treeCount = view.getUint32(16, true);
  const nodeCount = view.getUint32(20, true);
  const sigmoidScale = view.getFloat64(24, true);
  const flags = view.getUint32(32, true);
  const averageOutput = (flags & 1) !== 0;
  const rootsOffset = HEADER_BYTES;
  const nodesOffset = rootsOffset + treeCount * 4;
  const expectedBytes = nodesOffset + nodeCount * NODE_BYTES;
  if (bytes.byteLength !== expectedBytes) {
    throw new Error(`completed model asset size mismatch: expected ${expectedBytes}, got ${bytes.byteLength}`);
  }

  const predictRaw = (features: readonly number[]): number => {
    if (features.length !== featureCount) {
      throw new Error(`completed model feature count mismatch: expected ${featureCount}, got ${features.length}`);
    }

    let total = 0;
    for (let tree = 0; tree < treeCount; tree += 1) {
      let node = view.getUint32(rootsOffset + tree * 4, true);
      let safety = 0;
      while (true) {
        if (node >= nodeCount) throw new Error(`completed model node index out of range: ${node}`);
        const offset = nodesOffset + node * NODE_BYTES;
        const type = view.getUint8(offset);
        const featureIndex = view.getUint8(offset + 1);
        const nodeFlags = view.getUint8(offset + 2);
        const missingType = view.getUint8(offset + 3);
        const left = view.getInt32(offset + 4, true);
        const right = view.getInt32(offset + 8, true);
        const value = view.getFloat64(offset + 12, true);

        if (type === 1) {
          total += value;
          break;
        }
        if (type !== 0) throw new Error(`unsupported completed model node type: ${type}`);
        if (featureIndex >= featureCount) throw new Error(`completed model feature index out of range: ${featureIndex}`);

        const featureValue = features[featureIndex] ?? Number.NaN;
        const isMissing = missingType === 1
          ? Number.isNaN(featureValue)
          : missingType === 2
            ? Number.isNaN(featureValue) || featureValue === 0
            : false;
        const defaultLeft = (nodeFlags & 1) !== 0;
        const goLeft = isMissing ? defaultLeft : featureValue <= value;
        node = goLeft ? left : right;

        safety += 1;
        if (safety > 4096) throw new Error("completed model tree traversal exceeded safety bound");
      }
    }

    return averageOutput && treeCount > 0 ? total / treeCount : total;
  };

  return {
    featureCount,
    treeCount,
    nodeCount,
    predict(features: readonly number[]): number {
      const probability = sigmoid(predictRaw(features), sigmoidScale);
      if (!Number.isFinite(probability)) throw new Error("completed model produced a non-finite probability");
      return Math.min(1 - 1e-6, Math.max(1e-6, probability));
    },
  };
}
