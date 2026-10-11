import os


def allowed_origins() -> list[str]:
    """Return explicitly configured CORS origins; never fall back to wildcard."""
    value = os.getenv("ALLOWED_ORIGINS", "")
    return [origin.strip() for origin in value.split(",") if origin.strip()]


def database_path() -> str:
    """SQLite is sufficient for the local MVP; production can replace this repository."""
    return os.getenv("DATABASE_PATH", "twin.sqlite3")


def auth_mode() -> str:
    return os.getenv("AUTH_MODE", "development").lower()
