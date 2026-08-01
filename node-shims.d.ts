declare module "node:fs" {
  export function readFileSync(path: URL | string, encoding: "utf8"): string;
}

declare module "node:assert" {
  interface AssertStrict {
    equal(actual: unknown, expected: unknown, message?: string): void;
    ok(value: unknown, message?: string): asserts value;
    throws(fn: () => unknown, expected?: RegExp): void;
  }
  export const strict: AssertStrict;
}
