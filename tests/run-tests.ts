import { readFileSync } from "node:fs";
import { strict as assert } from "node:assert";
import { classifyHtml } from "../src/core/classify.js";
import { validateJraUrl } from "../src/core/security.js";
import { probeJraUrl } from "../src/core/probe.js";

const fixture = (name: string): string => readFileSync(new URL(`../../tests/fixtures/${name}`, import.meta.url), "utf8");

const result = classifyHtml(fixture("result.html"));
assert.equal(result.pageKind, "race-result");
assert.ok(result.confidence >= 0.8);
assert.equal(result.blockedReason, null);

const entry = classifyHtml(fixture("entry.html"));
assert.equal(entry.pageKind, "race-entry");
assert.ok(entry.confidence >= 0.8);

const blocked = classifyHtml(fixture("blocked.html"));
assert.equal(blocked.pageKind, "blocked");
assert.equal(blocked.confidence, 1);

assert.equal(validateJraUrl("https://www.jra.go.jp/robots.txt").hostname, "www.jra.go.jp");
assert.throws(() => validateJraUrl("http://www.jra.go.jp/"), /HTTPS_REQUIRED/);
assert.throws(() => validateJraUrl("https://example.com/"), /HOST_NOT_ALLOWED/);

const mockFetch = async (): Promise<Response> => new Response(fixture("result.html"), {
  status: 200,
  headers: { "content-type": "text/html; charset=utf-8" }
});
const probed = await probeJraUrl("https://www.jra.go.jp/example", mockFetch);
assert.equal(probed.ok, true);
assert.equal(probed.evidence.pageKind, "race-result");
assert.equal(probed.httpStatus, 200);
assert.equal(probed.bodySha256.length, 64);

let redirectCalls = 0;
const redirectToUntrusted = async (): Promise<Response> => {
  redirectCalls += 1;
  return new Response(null, { status: 302, headers: { location: "https://example.com/steal" } });
};
const redirectResult = await probeJraUrl("https://www.jra.go.jp/example", redirectToUntrusted);
assert.equal(redirectResult.ok, false);
assert.equal(redirectResult.errorCode, "HOST_NOT_ALLOWED");
assert.equal(redirectCalls, 1);

console.log("Phase 0 core tests passed.");
