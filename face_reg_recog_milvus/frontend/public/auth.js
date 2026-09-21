// Signing in against Authentik, with the Authorization Code flow and PKCE.
//
// No client secret exists here, and none could: everything this file does is
// readable by anyone who opens the page. PKCE is what makes that safe. The browser
// invents a random `code_verifier`, sends only its SHA-256 hash when it asks for a
// login, and reveals the verifier itself only when it trades the returned code for
// a token. Anyone who steals the code alone cannot use it.
//
// Loaded before app.js, which uses accessToken() on every request.

// sessionStorage, not localStorage: the token dies with the tab instead of waiting
// on disk for the next person at this machine. It still survives navigation between
// the three pages, which localStorage would also do but for far longer than wanted.
const TOKEN_KEY = "faceAccessToken";
const VERIFIER_KEY = "facePkceVerifier";
const STATE_KEY = "facePkceState";
const RETURN_KEY = "faceReturnTo";

// Authentik is configured with exactly one redirect URI, so every login lands on
// this page and is sent back afterwards to wherever it started.
const REDIRECT_PATH = "/enroll.html";
// `groups` is the one that matters: without it the token carries no groups claim and
// the API refuses every route with 403.
const SCOPES = "openid email profile groups";

/** The token this tab holds. Empty until somebody signs in. */
function accessToken() {
  return sessionStorage.getItem(TOKEN_KEY) || "";
}

/**
 * base64url, which is what OAuth asks for: no `=` padding, and `-` `_` in place of
 * `+` `/`, so the value survives being put in a URL.
 */
function base64url(bytes) {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/**
 * Authentik's OIDC endpoints.
 *
 * Built from the issuer's ORIGIN, not by appending to the issuer. Authentik puts
 * jwks under the application slug but keeps authorize and token above it, so
 * `new URL("authorize/", issuer)` would give a path that does not exist.
 */
function endpoints(issuer) {
  return {
    authorize: new URL("/application/o/authorize/", issuer).href,
    token: new URL("/application/o/token/", issuer).href,
  };
}

/** The issuer and client id, from the API. Asked once per tab. */
let configPromise = null;
function authConfig() {
  configPromise ??= fetch("/api/v1/auth/config").then((response) => {
    if (!response.ok) throw new Error("the API did not say where to log in");
    return response.json();
  });
  return configPromise;
}

/**
 * Make a PKCE verifier and the challenge that goes with it.
 *
 * Returns {verifier, challenge}. The verifier stays in this browser; only the
 * challenge is sent when the login starts.
 *
 * RFC 7636 defines the challenge as
 *
 *     BASE64URL(SHA256(ASCII(code_verifier)))
 *
 * and the code_verifier is the base64url TEXT, not the bytes it was made from. So
 * the text is encoded back to bytes before hashing. Hashing the original 32 bytes
 * instead gives a challenge that looks perfectly valid and that Authentik will
 * reject at the token exchange, with only `invalid_grant` to say why.
 * scripts/check_pkce.mjs holds the worked example from the RFC.
 */
async function pkcePair() {
  const verifier = base64url(crypto.getRandomValues(new Uint8Array(32)));
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return { verifier, challenge: base64url(digest) };
}

/** Send the browser to Authentik to sign in. */
async function login() {
  const config = await authConfig();
  const { verifier, challenge } = await pkcePair();
  // state ties the reply to this request. It is not PKCE, and PKCE does not replace
  // it: state stops a login being started by somebody else's link.
  const state = base64url(crypto.getRandomValues(new Uint8Array(16)));

  sessionStorage.setItem(VERIFIER_KEY, verifier);
  sessionStorage.setItem(STATE_KEY, state);
  sessionStorage.setItem(RETURN_KEY, location.pathname);

  const url = new URL(endpoints(config.issuer).authorize);
  url.search = new URLSearchParams({
    response_type: "code",
    client_id: config.client_id,
    redirect_uri: new URL(REDIRECT_PATH, location.origin).href,
    scope: SCOPES,
    state,
    code_challenge: challenge,
    code_challenge_method: "S256",
  });
  location.assign(url.href);
}

/**
 * Finish a login, when this page load is the redirect back from Authentik.
 *
 * Returns true if it handled a code, which means a navigation is already under way
 * and the caller should stop.
 */
async function completeLogin() {
  const params = new URLSearchParams(location.search);
  const code = params.get("code");
  if (!code) return false;

  const expected = sessionStorage.getItem(STATE_KEY);
  const verifier = sessionStorage.getItem(VERIFIER_KEY);
  // Single use, whatever happens next.
  sessionStorage.removeItem(STATE_KEY);
  sessionStorage.removeItem(VERIFIER_KEY);
  if (!expected || params.get("state") !== expected) {
    throw new Error("the login reply does not match the request this browser made");
  }

  const config = await authConfig();
  const response = await fetch(endpoints(config.issuer).token, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code,
      // Sent again, and Authentik checks it matches the one the code was issued
      // for. The token request carries no secret, so this is part of what ties the
      // exchange back to the original login.
      redirect_uri: new URL(REDIRECT_PATH, location.origin).href,
      client_id: config.client_id,
      code_verifier: verifier,
    }),
  });
  if (!response.ok) throw new Error("Authentik refused the token request");

  const token = await response.json();
  sessionStorage.setItem(TOKEN_KEY, token.access_token);

  // Leave, so the used code does not stay in the address bar or in history.
  const back = sessionStorage.getItem(RETURN_KEY) || REDIRECT_PATH;
  sessionStorage.removeItem(RETURN_KEY);
  location.replace(back);
  return true;
}

/** Drop the token. Authentik still has its own session, so signing in again is quick. */
function logout() {
  sessionStorage.removeItem(TOKEN_KEY);
  location.replace(REDIRECT_PATH);
}

/**
 * The claims inside the token, read WITHOUT verifying the signature.
 *
 * For drawing a username in the header, and nothing else. The browser cannot check
 * a token in any way it could not also fake; the API is what verifies it.
 */
function tokenClaims() {
  const token = accessToken();
  if (!token) return null;
  try {
    const payload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(payload));
  } catch {
    return null;
  }
}
