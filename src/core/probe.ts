import { classifyHtml } from "./classify.js";
import { sha256Hex } from "./hash.js";
import { validateJraUrl } from "./security.js";
import type { ProbeResult } from "./types.js";

const MAX_BODY_BYTES = 2_000_000;
const FETCH_TIMEOUT_MS = 15_000;
const MAX_REDIRECTS = 3;

export interface FetchLike {
  (input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
}

interface ReadResult {
  text: string;
  bytes: number;
  exceeded: boolean;
}

async function readTextWithLimit(response: Response, limitBytes: number): Promise<ReadResult> {
  if (!response.body) {
    const text = await response.text();
    const bytes = new TextEncoder().encode(text).byteLength;
    return { text: bytes > limitBytes ? text.slice(0, 100_000) : text, bytes, exceeded: bytes > limitBytes };
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const chunks: string[] = [];
  let bytes = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    bytes += value.byteLength;
    if (bytes > limitBytes) {
      await reader.cancel("body limit exceeded");
      return { text: chunks.join(""), bytes, exceeded: true };
    }
    chunks.push(decoder.decode(value, { stream: true }));
  }

  chunks.push(decoder.decode());
  return { text: chunks.join(""), bytes, exceeded: false };
}

async function fetchWithValidatedRedirects(initialUrl: URL, fetchImpl: FetchLike, signal: AbortSignal): Promise<{ response: Response; finalUrl: URL }> {
  let currentUrl = initialUrl;

  for (let redirects = 0; redirects <= MAX_REDIRECTS; redirects += 1) {
    const response = await fetchImpl(currentUrl, {
      redirect: "manual",
      signal,
      headers: {
        Accept: "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
        "Accept-Language": "ja,en;q=0.5",
        "Cache-Control": "no-cache",
        "User-Agent": "race-tantei-phase0/0.1 (non-commercial feasibility probe)"
      }
    });

    if (![301, 302, 303, 307, 308].includes(response.status)) return { response, finalUrl: currentUrl };
    const location = response.headers.get("location");
    if (!location) throw new Error("REDIRECT_WITHOUT_LOCATION");
    if (redirects === MAX_REDIRECTS) throw new Error("TOO_MANY_REDIRECTS");
    currentUrl = validateJraUrl(new URL(location, currentUrl).toString());
  }

  throw new Error("TOO_MANY_REDIRECTS");
}

export async function probeJraUrl(rawUrl: string, fetchImpl: FetchLike = fetch): Promise<ProbeResult> {
  const started = Date.now();
  const fetchedAt = new Date().toISOString();
  let sourceUrl = rawUrl;

  try {
    const initialUrl = validateJraUrl(rawUrl);
    sourceUrl = initialUrl.toString();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

    let response: Response;
    let finalUrl: URL;
    try {
      ({ response, finalUrl } = await fetchWithValidatedRedirects(initialUrl, fetchImpl, controller.signal));
    } finally {
      clearTimeout(timer);
    }

    sourceUrl = finalUrl.toString();
    const body = await readTextWithLimit(response, MAX_BODY_BYTES);
    const contentType = response.headers.get("content-type");

    if (body.exceeded) {
      return { ok: false, sourceUrl, fetchedAt, httpStatus: response.status, contentType, elapsedMs: Date.now() - started, bodyBytes: body.bytes, bodySha256: await sha256Hex(body.text), evidence: classifyHtml("", contentType), errorCode: "BODY_TOO_LARGE", errorMessage: `Response exceeded ${MAX_BODY_BYTES} bytes.` };
    }

    const evidence = classifyHtml(body.text, contentType);
    const ok = response.ok && evidence.pageKind !== "blocked" && evidence.pageKind !== "unknown";
    return { ok, sourceUrl, fetchedAt, httpStatus: response.status, contentType, elapsedMs: Date.now() - started, bodyBytes: body.bytes, bodySha256: await sha256Hex(body.text), evidence, errorCode: ok ? null : response.ok ? "UNRECOGNIZED_OR_BLOCKED" : `HTTP_${response.status}`, errorMessage: ok ? null : `Page classification: ${evidence.pageKind}` };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const timedOut = error instanceof DOMException && error.name === "AbortError";
    return { ok: false, sourceUrl, fetchedAt, httpStatus: 0, contentType: null, elapsedMs: Date.now() - started, bodyBytes: 0, bodySha256: "", evidence: classifyHtml("", null), errorCode: timedOut ? "FETCH_TIMEOUT" : message, errorMessage: timedOut ? "Request timed out." : message };
  }
}
