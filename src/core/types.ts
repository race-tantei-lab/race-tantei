export type PageKind = "race-result" | "race-entry" | "robots" | "blocked" | "unknown";

export interface ProbeEvidence {
  pageKind: PageKind;
  confidence: number;
  markersFound: string[];
  markersMissing: string[];
  title: string | null;
  normalizedTextLength: number;
  looksLikeHtml: boolean;
  blockedReason: string | null;
}

export interface ProbeResult {
  ok: boolean;
  sourceUrl: string;
  fetchedAt: string;
  httpStatus: number;
  contentType: string | null;
  elapsedMs: number;
  bodyBytes: number;
  bodySha256: string;
  evidence: ProbeEvidence;
  errorCode: string | null;
  errorMessage: string | null;
}
