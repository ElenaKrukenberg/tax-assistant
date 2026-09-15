"""Who is asking: Supabase JWT verification against the project's JWKS.

The frontend signs the user in with Supabase (magic link, ADR 0003) and sends the
resulting access token as a Bearer header. This project's tokens are signed
asymmetrically (ES256), so there is no shared secret to hold anywhere: the public
key is fetched from the project's JWKS endpoint and cached by PyJWKClient, keyed by
the token's `kid` — a key rotation on Supabase's side needs no change here.

What verification means concretely, because each check earns its place:

- the signature, against the JWKS key — the token really is this project's;
- `exp` — a stolen token stops working when it expires;
- `aud = "authenticated"` — a Supabase anon token (role `anon`, same signature)
  does not open anybody's tax case.

The user id is the `sub` claim. Everything downstream — the repository's WHERE,
the row-level-security role switch — keys off this one verified value, which is
why this module is the only place a token is ever read.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

import jwt
import structlog
from fastapi import Depends, HTTPException, Request
from jwt import PyJWKClient

from core.config import get_settings

logger = structlog.get_logger(__name__)

_LEEWAY_SECONDS = 30  # clock skew between Supabase and this host


class AuthNotConfigured(RuntimeError):
    """No SUPABASE_JWKS_URL. The chat tab works without it; Tax Cases do not."""


@lru_cache()
def _jwk_client() -> PyJWKClient:
    url = get_settings().supabase_jwks_url
    if not url:
        raise AuthNotConfigured(
            "SUPABASE_JWKS_URL is empty — see packages/backend/db/README.md"
        )
    # PyJWKClient caches keys and refetches on an unknown kid, which is exactly
    # the behaviour a key rotation needs.
    return PyJWKClient(url, cache_keys=True, lifespan=3600)


def verify_token(token: str) -> str:
    """The user id from a verified token, or HTTPException — never a guess."""
    try:
        key = _jwk_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
            leeway=_LEEWAY_SECONDS,
            options={"require": ["exp", "sub"]},
        )
    except AuthNotConfigured:
        raise HTTPException(503, detail="authentication is not configured")
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, detail="token expired")
    except jwt.PyJWTError as exc:
        # One class for everything else on purpose: which check failed is logged
        # for us, not reported to the caller — a precise rejection message is a
        # forgery-debugging aid.
        logger.info("token_rejected", reason=type(exc).__name__)
        raise HTTPException(401, detail="invalid token")

    return str(claims["sub"])


async def current_user(request: Request) -> str:
    """FastAPI dependency: the verified user id, from the Authorization header."""
    header: Optional[str] = request.headers.get("authorization")
    if not header or not header.lower().startswith("bearer "):
        raise HTTPException(401, detail="missing bearer token")
    return verify_token(header.split(" ", 1)[1].strip())


CurrentUser = Depends(current_user)
