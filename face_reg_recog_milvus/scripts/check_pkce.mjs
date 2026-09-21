// Self-check for pkcePair() in frontend/public/auth.js.
//
//     node scripts/check_pkce.mjs
//
// A wrong challenge is not visible anywhere: it is a valid-looking base64url string,
// and the only symptom is Authentik answering `invalid_grant` at the token exchange,
// long after the mistake. So it is checked against the worked example in RFC 7636
// Appendix B, which gives one verifier and the one challenge it must produce.
//
// No test framework, and none wanted: the repository has no JavaScript tooling, and
// this is one assertion.

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

// auth.js is a plain script for a <script> tag, so it exports nothing. Load the text
// and add the exports, rather than keeping a second copy of the function here that
// could quietly drift away from the one actually served.
const source = await readFile(new URL("../frontend/public/auth.js", import.meta.url), "utf8");
const auth = await import(
  "data:text/javascript," + encodeURIComponent(`${source}\nexport { pkcePair, base64url };`)
);

// RFC 7636 Appendix B.
const RFC_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk";
const RFC_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM";

const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(RFC_VERIFIER));
assert.equal(auth.base64url(digest), RFC_CHALLENGE, "base64url or the digest input is wrong");

// And the generated pair agrees with the same rule.
const pair = await auth.pkcePair();
const expected = auth.base64url(
  await crypto.subtle.digest("SHA-256", new TextEncoder().encode(pair.verifier)),
);
assert.equal(pair.challenge, expected, "the challenge is not the hash of the verifier text");
assert.equal(pair.verifier.length, 43, "RFC 7636 wants 43 to 128 characters");
assert.notEqual(pair.verifier, (await auth.pkcePair()).verifier, "the verifier is not random");

process.stdout.write("pkce ok\n");
