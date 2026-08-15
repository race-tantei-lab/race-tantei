interface D1Result<T = Record<string, unknown>> {
  success: boolean;
  results: T[];
  meta?: Record<string, unknown>;
}

interface D1ExecResult {
  count: number;
  duration: number;
}

interface D1PreparedStatement {
  bind(...values: unknown[]): D1PreparedStatement;
  run<T = Record<string, unknown>>(): Promise<D1Result<T>>;
  first<T = Record<string, unknown>>(column?: string): Promise<T | null>;
  all<T = Record<string, unknown>>(): Promise<D1Result<T>>;
}

interface D1Database {
  prepare(query: string): D1PreparedStatement;
  batch<T = any>(statements: D1PreparedStatement[]): Promise<D1Result<T>[]>;
  exec(query: string): Promise<D1ExecResult>;
}

interface FetcherResponse extends Response {
  json<T = unknown>(): Promise<T>;
}

interface Fetcher {
  fetch(request: Request): Promise<FetcherResponse>;
}

interface ExecutionContext {
  waitUntil(promise: Promise<unknown>): void;
  passThroughOnException(): void;
}

interface ScheduledController {
  scheduledTime: number;
  cron: string;
}

interface ExportedHandler<Env = unknown> {
  fetch?(request: Request, env: Env, ctx: ExecutionContext): Response | Promise<Response>;
  scheduled?(controller: ScheduledController, env: Env, ctx: ExecutionContext): void | Promise<void>;
}
