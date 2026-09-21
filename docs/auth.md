# Authentication and authorization

Authentik holds the accounts. The API holds no passwords, no user table and no shared
key. It receives an access token that Authentik signed, checks the signature against
Authentik's published public key, and reads the caller's identity out of the claims.

Two separate questions, two separate answers:

| Question | Decided by | Failure |
| --- | --- | --- |
| Who is this? | the token's signature, issuer, audience and expiry | **401** |
| May they do this? | the `groups` claim | **403** |

## Roles

| Group | May |
| --- | --- |
| `face-operator` | identify a face, read the registered population |
| `face-admin` | everything an operator may, and register or unregister a person |

An account in neither group is refused with 403 on every `/api/v1` route. Reading the
registry needs a group because the rows are names, birthdates and face images of real
people.

Group names come from `OIDC_ADMIN_GROUP` and `OIDC_OPERATOR_GROUP`.

## Open routes

`/health` and `/health/ready`, because a load balancer probe cannot carry a token, and
`/api/v1/auth/config`, because the browser must read it before it can obtain one. That
endpoint returns only the issuer and the client id, both of which appear in the address
bar during every login.

## Setting up Authentik

Start it, then open `http://localhost:9000/if/flow/initial-setup/` once to create the
first administrator.

```bash
echo "AUTHENTIK_SECRET_KEY=$(openssl rand -hex 32)" >> .env
echo "AUTHENTIK_POSTGRES_PASSWORD=$(openssl rand -hex 16)" >> .env
docker compose up -d authentik-postgres authentik-server authentik-worker
```

The worker runs the database migrations. If the server answers 500 on the first load,
watch `docker compose logs -f authentik-worker` until they finish.

Then, in the Authentik admin interface:

1. **Directory -> Groups**: create `face-admin` and `face-operator`, and put your
   account in one of them.
2. **Applications -> Providers -> Create -> OAuth2/OpenID Provider**:
   - Client type **Public**. A browser cannot keep a secret, and this is what makes
     PKCE required rather than optional.
   - Redirect URI, **Strict**: `https://localhost:8443/enroll.html`
   - Scopes: `openid`, `email`, `profile`, and the **groups** mapping.
   - Advanced protocol settings, **Signing Key**: choose the self-signed certificate.
3. **Applications -> Create**: slug `face-api`, bound to that provider.
4. Copy the client id and the issuer into `.env` as `OIDC_CLIENT_ID` and `OIDC_ISSUER`.

## Calling the API from a script

A browser signs in through the pages. A script needs its own token, which means a
service account in Authentik rather than a person's login. Add the service account to
`face-admin` or `face-operator`, give it a token, and let it obtain an access token
through whichever grant its provider allows; the public provider the pages use is
configured for the authorization code flow only, so a machine client wants a second,
confidential provider of its own.

Whatever issues it, the call is the same:

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/persons
```

## In the browser

The pages use the authorization code flow with PKCE, in
[`frontend/public/auth.js`](../face_reg_recog_milvus/frontend/public/auth.js).

The browser makes a random `code_verifier`, sends only its SHA-256 hash to start the
login, and reveals the verifier itself when it trades the returned code for a token.
A stolen code is therefore useless on its own, which is what lets a page with no
secret in it do this safely.

The token goes in `sessionStorage`: it dies with the tab, instead of waiting on disk
for the next person at that machine.

## Things that will catch you

**The provider has no signing key.** Authentik then issues opaque tokens instead of
JWTs, and the API rejects every one of them. The symptom is a successful login
followed by 401 on every request.

**The `groups` scope is not on the provider.** The token carries no `groups` claim,
every route answers 403, and the login itself looked perfect.

**The redirect URI does not match exactly.** Authentik compares the whole string,
including the scheme and the port. The pages always redirect to `/enroll.html`, and
send the browser back afterwards to wherever it started.

**The challenge is the hash of the wrong thing.** `code_challenge` is
`BASE64URL(SHA256(ASCII(code_verifier)))`, where the verifier is the base64url *text*,
not the random bytes it was made from. Hashing the bytes gives a valid-looking
challenge that fails at the token exchange with only `invalid_grant` to explain it.
`scripts/check_pkce.mjs` checks this against the worked example in RFC 7636.

**The API container cannot resolve the public issuer.** The `iss` claim must match the
public URL exactly, but the key fetch is a server-to-server call. `OIDC_JWKS_URL`
exists to point that one request at the compose service name instead.
