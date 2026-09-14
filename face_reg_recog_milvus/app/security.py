"""
API key authentication.

One shared key, sent in a header, checked on every /api/v1 route. Health checks stay
open, because a load balancer probe cannot carry a secret.

This is the smallest thing that closes the hole. It gives no per-user identity and no
way to revoke one client without changing the key for all of them. Anything that needs
those wants real accounts instead.
"""

import logging
import secrets

from fastapi import Security
from fastapi.security import APIKeyHeader

from app.config import API_KEY
from app.errors import AuthenticationError

logger = logging.getLogger("security")

API_KEY_NAME = "X-API-Key"

# auto_error=False so that a missing header arrives here as None instead of raising
# a bare HTTPException. That keeps every failure in one error shape.
_api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


def keys_match(supplied: str, expected: str) -> bool:
    """
    Say whether the supplied key is the expected one.

    Not `supplied == expected`. Python stops comparing two strings at the first
    difference, so a wrong key that shares more leading characters takes slightly
    longer to reject. Measured over many requests, that difference gives the key
    away one character at a time. compare_digest always takes the same time.

    It raises TypeError on a non-string, which is why the caller turns a missing
    header into "" first. It hides content timing, not length timing, and that is
    accepted here because the length of the key is not the secret.
    """
    return secrets.compare_digest(supplied, expected)


async def require_api_key(supplied: str | None = Security(_api_key_header)) -> None:
    """Reject the request unless it carries the right key."""
    if not keys_match(supplied or "", API_KEY):
        raise AuthenticationError(f"a valid {API_KEY_NAME} header is required")
