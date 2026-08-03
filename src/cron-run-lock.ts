const LOCK_MAX_AGE_MS = 90_000;

let cronStartedAt = 0;

export type CronLockResult = {
  acquired: boolean;
  recoveredStaleLock: boolean;
};

export function tryStartCronRun(now = Date.now()): CronLockResult {
  if (cronStartedAt === 0) {
    cronStartedAt = now;
    return { acquired: true, recoveredStaleLock: false };
  }

  if (now - cronStartedAt >= LOCK_MAX_AGE_MS) {
    cronStartedAt = now;
    return { acquired: true, recoveredStaleLock: true };
  }

  return { acquired: false, recoveredStaleLock: false };
}

export function finishCronRun(): void {
  cronStartedAt = 0;
}
