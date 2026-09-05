import os


def database_url() -> str:
    """Read a SQLAlchemy URL, accepting the common PostgreSQL shorthand."""
    url = os.getenv("DATABASE_URL", "sqlite:///./sales_agent.db")
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


DATABASE_URL = database_url()
JWT_SECRET = os.getenv("JWT_SECRET", "development-only-change-me")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
EMAIL_SENDING_ENABLED = os.getenv("EMAIL_SENDING_ENABLED", "false").lower() == "true"
CORS_ORIGINS = tuple(
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
)
_INSECURE_SECRETS = {
    "development-only-change-me",
    "change-this-local-development-secret",
    "replace-with-a-long-random-value-before-production",
}


def validate_runtime_config() -> None:
    """Reject insecure configuration before serving production traffic."""
    if ENVIRONMENT not in {"development", "test", "production"}:
        raise RuntimeError("ENVIRONMENT must be development, test, or production")
    if JWT_EXPIRE_MINUTES <= 0:
        raise RuntimeError("JWT_EXPIRE_MINUTES must be positive")
    if ENVIRONMENT == "production":
        if DATABASE_URL.startswith("sqlite"):
            raise RuntimeError("Production requires a PostgreSQL DATABASE_URL")
        if len(JWT_SECRET) < 32 or JWT_SECRET in _INSECURE_SECRETS:
            raise RuntimeError("Production requires a unique JWT_SECRET of at least 32 characters")
        if not CORS_ORIGINS or "*" in CORS_ORIGINS:
            raise RuntimeError("Production requires explicit CORS_ORIGINS")
