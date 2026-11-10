from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import String, create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings
from .services.database import DatabaseURLError, engine_options


class Base(DeclarativeBase):
    pass


def fit_strings_to_columns(obj) -> None:
    """Trim text that's longer than its column allows.

    SQLite ignores VARCHAR lengths but Postgres rejects the whole save, so a 150-character hometown from a form
    must never turn into an error page there. Validation keeps normal input well under these limits."""
    mapper = inspect(obj).mapper
    for attr in mapper.column_attrs:
        col = attr.columns[0]
        length = getattr(col.type, "length", None) if isinstance(col.type, String) else None
        if not length:
            continue
        value = getattr(obj, attr.key, None)
        if isinstance(value, str) and len(value) > length:
            setattr(obj, attr.key, value[:length])


@event.listens_for(Session, "before_flush")
def _fit_strings(session: Session, flush_context, instances) -> None:
    for obj in list(session.new) + list(session.dirty):
        if isinstance(obj, Base):
            fit_strings_to_columns(obj)


_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def init_db(url: str | None = None) -> None:
    """Create the engine and tables. Safe to call more than once."""
    global _engine, _SessionLocal
    from . import models  # noqa: F401 - registers tables

    settings.ensure_dirs()
    opts = engine_options(url or settings.db_url)
    if opts.kind == "postgresql":
        try:
            import psycopg  # noqa: F401
        except ImportError:  # pragma: no cover - depends on what's installed
            raise DatabaseURLError(
                'PostgreSQL needs the psycopg driver: pip install -e ".[postgres]" (the Docker image includes it).'
            ) from None
    if _engine is not None:
        _engine.dispose()  # re-initialising (tests, demo) must not leave old connections holding locks
    _engine = create_engine(opts.url, connect_args=opts.connect_args, pool_pre_ping=opts.pool_pre_ping)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    Base.metadata.create_all(_engine)


def get_engine():
    if _engine is None:
        init_db()
    return _engine


def get_session() -> Iterator[Session]:
    if _SessionLocal is None:
        init_db()
    assert _SessionLocal is not None
    with _SessionLocal() as session:
        yield session


def session_scope() -> Session:
    if _SessionLocal is None:
        init_db()
    assert _SessionLocal is not None
    return _SessionLocal()
