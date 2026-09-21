"""
Per-user authentication and authorization, backed by Authentik over OIDC.

Authentik owns the users, the groups and the passwords. This service never sees a
credential. It receives an access token -- a JWT that Authentik signed with its
private key -- and verifies it offline against the public keys Authentik publishes.
So a request costs one signature check, not a round trip to the identity provider.

Two separate questions, two separate failures:

  authentication  "who is this"        -> a verified token becomes a User, else 401
  authorization   "may they do this"   -> their groups against the route's, else 403

A route asks for the second with require_admin or require_operator.
"""

import logging
from dataclasses import dataclass
from typing import Annotated

import anyio.to_thread
import jwt
from fastapi import Depends, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import (
    OIDC_ADMIN_GROUP,
    OIDC_CLIENT_ID,
    OIDC_ISSUER,
    OIDC_JWKS_URL,
    OIDC_OPERATOR_GROUP,
)
from app.errors import AuthenticationError, AuthorizationError

logger = logging.getLogger("security")

# Pinned, and never read from the token's own header. A token that asks to be checked
# with "none", or with HMAC using the public key as the shared secret, is the classic
# way to forge one. PyJWT only accepts what is named here.
ALGORITHM = "RS256"

# auto_error=False so a missing header arrives here as None instead of raising a bare
# HTTPException. That keeps every failure in the one {error, detail} response shape.
_bearer = HTTPBearer(auto_error=False, description="Authentik access token")

# PyJWT fetches the key set on the first token and caches it, so an ordinary request
# does no network I/O. It refetches when a token names a key id it has not seen,
# which is what makes Authentik's key rotation invisible here.
_jwks = jwt.PyJWKClient(OIDC_JWKS_URL, cache_keys=True) if OIDC_JWKS_URL else None


@dataclass(frozen=True)
class User:
    """The caller, as their token describes them."""

    # Authentik's own opaque user id. Stable: it survives a rename or a new email
    # address, which is why authorization and audit records should key on it.
    sub: str
    email: str
    username: str
    groups: frozenset[str]


def verify_token(token: str) -> dict:
    """
    Check that the token really came from Authentik, unaltered and still valid, and
    return its claims.

    Raises a jwt.PyJWTError subclass when anything at all is wrong. The caller turns
    every one of those into the same 401, so a probe learns nothing from the reply.
    """
    # Reads the token's `kid` header and hands back the matching public key, fetching
    # the key set first if it is not cached.
    signing_key = _jwks.get_signing_key_from_jwt(token).key

    return jwt.decode(
        token,
        signing_key,
        # A list this service controls, never the token's own `alg` header.
        algorithms=[ALGORITHM],
        # Authentik can serve many applications from one issuer, and signs every one
        # of their tokens with the same key. Without this check, a token minted for
        # any other application on the same Authentik would verify here.
        audience=OIDC_CLIENT_ID,
        issuer=OIDC_ISSUER,
        # PyJWT checks a claim only when the claim is there. Listing them here makes
        # an absent claim fatal instead of silently acceptable.
        options={"require": ["exp", "iss", "sub", "aud"]},
    )


async def require_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)],
) -> User:
    """Turn the Authorization header into a User, or refuse the request."""
    if _jwks is None:
        raise AuthenticationError("this server has no OIDC issuer configured")
    if credentials is None:
        raise AuthenticationError("an 'Authorization: Bearer <token>' header is required")
    try:
        # verify_token blocks on a cold cache or a key rotation. Run it off the event
        # loop, so that one such request cannot stall every other request in flight.
        claims = await anyio.to_thread.run_sync(verify_token, credentials.credentials)
    except jwt.PyJWTError as exc:
        # Log the real reason, tell the caller nothing. "wrong audience" and "expired"
        # are different facts, and handing them back is a tool for probing.
        logger.info("token rejected: %s", exc)
        raise AuthenticationError("the access token is missing, expired or not valid") from exc

    return User(
        sub=claims["sub"],
        email=claims.get("email", ""),
        username=claims.get("preferred_username", ""),
        # A token with no groups claim gives an empty set, so the caller fails every
        # group check rather than passing them all.
        groups=frozenset(claims.get("groups", [])),
    )


def require_groups(*allowed: str):
    """
    Build a dependency that admits a caller who is in any one of `allowed`.

    A factory, because the permitted groups differ per route while a FastAPI
    dependency takes no arguments of its own.
    """

    async def check(user: Annotated[User, Depends(require_user)]) -> User:
        if user.groups.isdisjoint(allowed):
            logger.info("denied %s: has %s, needs one of %s", user.sub, sorted(user.groups), allowed)
            raise AuthorizationError(f"this action needs one of these groups: {', '.join(allowed)}")
        return user

    return check


# The whole access policy, in one place instead of spread over the routes.
# An admin changes the registered population; an operator only identifies against it.
require_admin = require_groups(OIDC_ADMIN_GROUP)
require_operator = require_groups(OIDC_ADMIN_GROUP, OIDC_OPERATOR_GROUP)

