import {
  acquireNamedLiveDeadlineLease,
  releaseNamedLiveDeadlineLease,
} from "./live-preview-safety.js";

export const ENTRY_REPAIR_LEASE_KEY = "entry-readiness-repair:v1";
export const ENTRY_REPAIR_LEASE_SECONDS = 360;

export async function acquireEntryRepairLease(db: D1Database, owner: string): Promise<boolean> {
  return acquireNamedLiveDeadlineLease(db, ENTRY_REPAIR_LEASE_KEY, owner, ENTRY_REPAIR_LEASE_SECONDS);
}

export async function releaseEntryRepairLease(db: D1Database, owner: string): Promise<void> {
  await releaseNamedLiveDeadlineLease(db, ENTRY_REPAIR_LEASE_KEY, owner);
}
