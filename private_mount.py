"""Mount the teammate's private-Twin backend (private_twins/backend) under /private.

B is a standalone FastAPI app whose package is named `app`. It has no lifespan or startup
hooks: its SQLite repository and creator registry initialise at import time, so mounting
needs no extra startup work. B's files are not edited; everything B needs from this service
(CORS, auth mode, database path) is arranged here, before B is imported.
"""
import os
import re
import sys

from fastapi import FastAPI, Header, HTTPException

BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "private_twins", "backend")
DEMO_USER_RE = re.compile(r"^[A-Za-z0-9_.:@\-]{1,100}$")


def demo_auth_enabled() -> bool:
    return os.environ.get("DEMO_AUTH", "") == "1"


def build_private_app() -> FastAPI:
    if BACKEND_DIR not in sys.path:
        sys.path.append(BACKEND_DIR)  # appended, so it can never shadow this service's modules

    # Demo defaults. AUTH_MODE=development trusts an X-Dev-User-Id header from any caller (see INTEGRATION.md);
    # set AUTH_MODE=clerk plus the CLERK_* variables for real token verification.
    os.environ.setdefault("AUTH_MODE", "development")
    # Always-writable path in the image; data resets on restart (demo twins live in code, not the database).
    os.environ.setdefault("DATABASE_PATH", "/tmp/twin.sqlite3")

    import app.config as b_config

    # One CORS layer only: this service's. Stop B from adding its own (allowlist-based) layer.
    original_origins = b_config.allowed_origins
    b_config.allowed_origins = lambda: []
    try:
        import app.main as b_main
    finally:
        b_config.allowed_origins = original_origins

    from app.services.auth import optional_user_id

    def demo_aware_user(
        authorization: str | None = Header(default=None),
        x_dev_user_id: str | None = Header(default=None),
        x_demo_user: str | None = Header(default=None),
    ) -> str | None:
        """DEMO_AUTH=1 (off by default) accepts `X-Demo-User: <id>` as the signed-in user.
        Otherwise this is exactly B's own auth."""
        if demo_auth_enabled() and x_demo_user is not None and x_demo_user.strip():
            user = x_demo_user.strip()
            if not DEMO_USER_RE.match(user):
                raise HTTPException(status_code=400, detail="X-Demo-User must be 1-100 chars of letters, digits, _ . : @ -")
            return user
        return optional_user_id(authorization, x_dev_user_id)

    b_main.app.dependency_overrides[optional_user_id] = demo_aware_user
    if demo_auth_enabled():
        print("WARNING: DEMO_AUTH=1 - /private accepts X-Demo-User as identity. Demo only.", file=sys.stderr)
    return b_main.app


def mount_private(app: FastAPI) -> None:
    app.mount("/private", build_private_app())
