"""Owner identity boundary. Clerk verification is enabled only in configured production mode."""

from __future__ import annotations

import os

from fastapi import Header, HTTPException, status

from app.config import auth_mode


def optional_user_id(
    authorization: str | None = Header(default=None),
    x_dev_user_id: str | None = Header(default=None),
) -> str | None:
    """Read a local development identity, or require Clerk JWT verification in production.

    The development header exists solely for local/Base44 prototype testing. It must not
    be enabled in a deployed environment.
    """
    if auth_mode() == "development":
        return x_dev_user_id.strip() if x_dev_user_id and x_dev_user_id.strip() else None
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        import jwt
        from jwt import PyJWKClient
    except ImportError as exc:  # pragma: no cover - configuration-only path
        raise HTTPException(status_code=503, detail="Clerk JWT support is not installed.") from exc
    token = authorization.removeprefix("Bearer ").strip()
    issuer = os.getenv("CLERK_JWT_ISSUER")
    jwks_url = os.getenv("CLERK_JWKS_URL")
    if not issuer or not jwks_url:
        raise HTTPException(status_code=503, detail="Clerk JWT verification is not configured.")
    try:  # Clerk session token subject is the stable user identifier.
        signing_key = PyJWKClient(jwks_url).get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, signing_key, algorithms=["RS256"], issuer=issuer, options={"verify_aud": False})
        subject = claims.get("sub")
    except Exception as exc:  # Do not reveal token-validation details.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Clerk session token.") from exc
    return str(subject) if subject else None


def require_user_id(user_id: str | None = None) -> str:
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in is required for private portfolios and conversations.")
    return user_id
