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
