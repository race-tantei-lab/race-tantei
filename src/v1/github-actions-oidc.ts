const GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com";
const GITHUB_OIDC_JWKS = `${GITHUB_OIDC_ISSUER}/.well-known/jwks`;
export const LIVE_DEADLINE_OIDC_AUDIENCE = "race-tantei-live-deadline";
const ALLOWED_REPOSITORY = "race-tantei-lab/race-tantei";
const ALLOWED_REF = "refs/heads/main";
const ALLOWED_EVENTS = new Set(["schedule", "workflow_dispatch", "push"]);
const ALLOWED_WORKFLOW_REFS = new Set([
  "race-tantei-lab/race-tantei/.github/workflows/live-deadline-external-watchdog.yml@refs/heads/main",
  "race-tantei-lab/race-tantei/.github/workflows/verify-live-deadline-production.yml@refs/heads/main",
]);
const CLOCK_SKEW_SECONDS = 90;
const JWKS_CACHE_MS = 6 * 60 * 60 * 1000;

type JwtHeader = { alg?: string; kid?: string; typ?: string };
type GithubOidcClaims = {
  iss?: string;
  aud?: string | string[];
  exp?: number;
  nbf?: number;
  iat?: number;
  sub?: string;
  repository?: string;
  ref?: string;
  event_name?: string;
  workflow_ref?: string;
};
type GithubJwk = JsonWebKey & { kid?: string; alg?: string };
type JwkSet = { keys?: GithubJwk[] };
type CachedJwks = { fetchedAt: number; keys: GithubJwk[] };
let cachedJwks: CachedJwks | null = null;

function decodeBase64Url(value: string): Uint8Array {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function decodeJson<T>(value: string): T {
  return JSON.parse(new TextDecoder().decode(decodeBase64Url(value))) as T;
}

async function loadJwks(force = false): Promise<GithubJwk[]> {
  const now = Date.now();
  if (!force && cachedJwks && now - cachedJwks.fetchedAt < JWKS_CACHE_MS) return cachedJwks.keys;
  const response = await fetch(GITHUB_OIDC_JWKS, { headers: { accept: "application/json" } });
  if (!response.ok) throw new Error(`GITHUB_OIDC_JWKS_HTTP_${response.status}`);
  const body = await response.json() as JwkSet;
  const keys = Array.isArray(body.keys) ? body.keys : [];
  if (!keys.length) throw new Error("GITHUB_OIDC_JWKS_EMPTY");
  cachedJwks = { fetchedAt: now, keys };
  return keys;
}

function audienceAllowed(aud: string | string[] | undefined): boolean {
  return Array.isArray(aud) ? aud.includes(LIVE_DEADLINE_OIDC_AUDIENCE) : aud === LIVE_DEADLINE_OIDC_AUDIENCE;
}

function claimsAllowed(claims: GithubOidcClaims, nowSeconds: number): boolean {
  if (claims.iss !== GITHUB_OIDC_ISSUER) return false;
  if (!audienceAllowed(claims.aud)) return false;
  if (claims.repository !== ALLOWED_REPOSITORY || claims.ref !== ALLOWED_REF) return false;
  if (!claims.event_name || !ALLOWED_EVENTS.has(claims.event_name)) return false;
  if (!claims.workflow_ref || !ALLOWED_WORKFLOW_REFS.has(claims.workflow_ref)) return false;
  if (!claims.sub?.startsWith(`repo:${ALLOWED_REPOSITORY}:`)) return false;
  if (!Number.isFinite(claims.exp) || Number(claims.exp) < nowSeconds - CLOCK_SKEW_SECONDS) return false;
  if (Number.isFinite(claims.nbf) && Number(claims.nbf) > nowSeconds + CLOCK_SKEW_SECONDS) return false;
  if (!Number.isFinite(claims.iat) || Number(claims.iat) > nowSeconds + CLOCK_SKEW_SECONDS) return false;
  return true;
}

async function verifyWithKeys(
  signingInput: string,
  signature: Uint8Array,
  kid: string,
  keys: GithubJwk[],
): Promise<boolean> {
  const matching = keys.filter((key) => key.kid === kid && (key.alg == null || key.alg === "RS256"));
  const signatureBytes = Uint8Array.from(signature);
  const signingBytes = new TextEncoder().encode(signingInput);
  for (const jwk of matching) {
    try {
      const key = await crypto.subtle.importKey(
        "jwk",
        jwk,
        { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
        false,
        ["verify"],
      );
      const ok = await crypto.subtle.verify(
        "RSASSA-PKCS1-v1_5",
        key,
        signatureBytes.buffer,
        signingBytes.buffer,
      );
      if (ok) return true;
    } catch {
      // Try another matching signing key. GitHub rotates OIDC keys.
    }
  }
  return false;
}

export async function verifyGithubActionsOidcAuthorization(authorization: string | null): Promise<GithubOidcClaims | null> {
  if (!authorization?.startsWith("Bearer ")) return null;
  const token = authorization.slice("Bearer ".length).trim();
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  let header: JwtHeader;
  let claims: GithubOidcClaims;
  try {
    header = decodeJson<JwtHeader>(parts[0]);
    claims = decodeJson<GithubOidcClaims>(parts[1]);
  } catch {
    return null;
  }
  if (header.alg !== "RS256" || !header.kid) return null;
  if (!claimsAllowed(claims, Math.floor(Date.now() / 1000))) return null;

  const signingInput = `${parts[0]}.${parts[1]}`;
  const signature = decodeBase64Url(parts[2]);
  let keys = await loadJwks(false);
  if (await verifyWithKeys(signingInput, signature, header.kid, keys)) return claims;

  // A key may have rotated between cached requests. Refresh once before rejecting.
  keys = await loadJwks(true);
  return await verifyWithKeys(signingInput, signature, header.kid, keys) ? claims : null;
}
