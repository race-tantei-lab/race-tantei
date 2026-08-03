const LOCK_MAX_AGE_MS = 90_000;

let cronStartedAt = 0;

export function tryStartCronRun(now = Date.now()): boolean {
  if (cronStartedAt === 0 || now - cronStartedAt >= LOCK_MAX_AGE_MS) {
    cronStartedAt = now;
    return true;
  }

  return false;
}

export function finishCronRun(): void {
  cronStartedAt = 0;
}
