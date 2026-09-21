"""
Login configuration: /api/v1/auth/config

Deliberately open. The browser cannot ask for a token until it knows where to ask
and under which client id, so this endpoint must answer before anyone is signed in.
Nothing here is secret: a public OAuth2 client has no client secret, and both values
appear in the address bar during every login.

Serving them, rather than writing them into the JavaScript, keeps one source of truth
in the environment. Point the API at a different Authentik and the pages follow, with
no rebuild of the frontend.
"""

import logging

from fastapi import APIRouter

from app.config import OIDC_CLIENT_ID, OIDC_ISSUER
from app.schemas import AuthConfig

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("routes.auth")


@router.get("/config", response_model=AuthConfig, summary="Where to log in")
async def auth_config() -> AuthConfig:
    """The issuer and client id the browser needs to begin an authorization code flow."""
    return AuthConfig(issuer=OIDC_ISSUER, client_id=OIDC_CLIENT_ID)
