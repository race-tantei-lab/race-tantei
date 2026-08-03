let cronRunning = false;

export function tryStartCronRun(): boolean {
  if (cronRunning) return false;
  cronRunning = true;
  return true;
}

export function finishCronRun(): void {
  cronRunning = false;
}
