import { getState, setState } from "./db.js";
import { THREE_MONTH_SCOPE_VERSION } from "./three-month-scope.js";
import { nowIso } from "./utils.js";

const STATE_KEY = "historical_audit:three_month:v2";
const AUDIT_VERSION = "three-month-stake-reconciliation-v2";

export interface HistoricalAuditState {
  valid: boolean;
  auditVersion: string;
  scopeVersion: string;
  modelVersion: string;
  checkedAt: string;
  findings: Record<string, number>;
}

function invalidState(modelVersion: string): HistoricalAuditState {
  return {
    valid: false,
    auditVersion: AUDIT_VERSION,
    scopeVersion: THREE_MONTH_SCOPE_VERSION,
    modelVersion,
    checkedAt: nowIso(),
    findings: {}
  };
}

export async function getHistoricalAuditState(
  db: D1Database,
  modelVersion: string
): Promise<HistoricalAuditState> {
  const raw = await getState(db, STATE_KEY);
  if (!raw) return invalidState(modelVersion);
  try {
    const parsed = JSON.parse(raw) as Partial<HistoricalAuditState>;
    const valid = parsed.valid === true
      && parsed.auditVersion === AUDIT_VERSION
      && parsed.scopeVersion === THREE_MONTH_SCOPE_VERSION
      && parsed.modelVersion === modelVersion;
    return {
      valid,
      auditVersion: parsed.auditVersion ?? AUDIT_VERSION,
      scopeVersion: parsed.scopeVersion ?? THREE_MONTH_SCOPE_VERSION,
      modelVersion: parsed.modelVersion ?? modelVersion,
      checkedAt: parsed.checkedAt ?? nowIso(),
      findings: parsed.findings && typeof parsed.findings === "object"
        ? Object.fromEntries(Object.entries(parsed.findings).map(([key, value]) => [key, Number(value ?? 0)]))
        : {}
    };
  } catch {
    return invalidState(modelVersion);
  }
}

export async function saveHistoricalAuditState(
  db: D1Database,
  modelVersion: string,
  audit: Record<string, any>
): Promise<HistoricalAuditState> {
  const findings = audit.findings && typeof audit.findings === "object"
    ? Object.fromEntries(Object.entries(audit.findings).map(([key, value]) => [key, Number(value ?? 0)]))
    : {};
  const state: HistoricalAuditState = {
    valid: audit.valid === true && audit.auditVersion === AUDIT_VERSION,
    auditVersion: String(audit.auditVersion ?? AUDIT_VERSION),
    scopeVersion: THREE_MONTH_SCOPE_VERSION,
    modelVersion,
    checkedAt: String(audit.generatedAt ?? nowIso()),
    findings
  };
  await setState(db, STATE_KEY, JSON.stringify(state));
  return state;
}
