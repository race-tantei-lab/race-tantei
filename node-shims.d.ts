declare module "node:assert" {
  export const strict: {
    equal(actual: unknown, expected: unknown, message?: string): void;
    deepEqual(actual: unknown, expected: unknown, message?: string): void;
    ok(value: unknown, message?: string): asserts value;
  };
}

declare const process: {
  exit(code?: number): never;
  env: Record<string, string | undefined>;
};
