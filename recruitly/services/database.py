"""Database URL rules: which databases Recruitly supports and how their URLs are written.

Pure functions, so they're unit tested without a database."""

from __future__ import annotations

from dataclasses import dataclass, field


class DatabaseURLError(ValueError):
    pass


@dataclass
class EngineOptions:
    url: str
    kind: str  # "sqlite" or "postgresql"
    connect_args: dict = field(default_factory=dict)
    pool_pre_ping: bool = False


def normalize_db_url(url: str) -> str:
    """Accept the URL forms people paste (Heroku/Render/Supabase style `postgres://...`) and pick the psycopg 3 driver.

    >>> normalize_db_url("postgres://u:p@db:5432/recruitly")
    'postgresql+psycopg://u:p@db:5432/recruitly'
    """
    url = (url or "").strip()
    if not url:
        raise DatabaseURLError("RECRUITLY_DB_URL is empty.")
    scheme, sep, rest = url.partition("://")
    if not sep:
        raise DatabaseURLError(f"RECRUITLY_DB_URL doesn't look like a database URL: {url!r}")
    scheme = scheme.lower()
    if scheme in ("postgres", "postgresql", "postgresql+psycopg", "postgresql+psycopg3"):
        return f"postgresql+psycopg://{rest}"
    if scheme.startswith("postgresql+"):
        # some other driver the user installed themselves (e.g. psycopg2): leave it alone
        return f"{scheme}://{rest}"
    if scheme == "sqlite" or scheme.startswith("sqlite+"):
        return url
    raise DatabaseURLError(
        f"Recruitly supports SQLite and PostgreSQL, not {scheme!r}. "
        "Use e.g. postgresql://user:password@host:5432/recruitly")


def engine_options(url: str) -> EngineOptions:
    """Normalized URL plus the connection settings that database needs."""
    url = normalize_db_url(url)
    if url.startswith("sqlite"):
        return EngineOptions(url=url, kind="sqlite", connect_args={"check_same_thread": False})
    # Postgres: keep the session in UTC so naive timestamps compare the same way as on SQLite,
    # and check pooled connections before use (a restarted db container would otherwise break the first request).
    return EngineOptions(url=url, kind="postgresql", connect_args={"options": "-c timezone=UTC"}, pool_pre_ping=True)


def redact_db_url(url: str) -> str:
    """The URL with any password replaced, safe to print in logs."""
    scheme, sep, rest = url.partition("://")
    if not sep or "@" not in rest:
        return url
    creds, _, host = rest.rpartition("@")
    user = creds.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}" if ":" in creds else url
