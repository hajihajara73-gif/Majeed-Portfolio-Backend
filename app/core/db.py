from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

# Synchronous SQLAlchemy on purpose. This is a single-author CMS with a handful
# of writes a week; async would add cancellation and connection-scope pitfalls
# for throughput nobody here will ever need. FastAPI runs sync dependencies in
# a threadpool, so the event loop is not blocked.
engine = create_engine(
    settings.sqlalchemy_url,
    # pool_pre_ping is deliberately OFF.
    #
    # It issues a `SELECT 1` on every checkout to prove the connection is
    # alive. Against a local database that is free; against Neon it is a full
    # round trip — measured at ~330 ms — added to EVERY request in the API.
    # `pool_recycle` achieves the same protection against stale connections
    # without paying that cost per request, and Neon's pooler already drops
    # dead sessions on its side.
    pool_pre_ping=False,
    pool_recycle=280,
    pool_size=5,
    max_overflow=5,
    # SQL echo prints every statement AND its bound parameters, which in this
    # schema means password hashes, session token hashes and TOTP secrets on
    # stdout. Gated on DEBUG *and* hard-disabled in production, so a stray
    # DEBUG=true in a deployment environment cannot turn the log into a
    # credential dump. `Settings` also refuses to start in that state.
    echo=settings.debug and settings.environment != "production",
)

SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)


def get_db() -> Generator[Session, None, None]:
    """
    Request-scoped session.

    Rolls back on any exception so a failed request can never leave a partial
    write behind, and always closes so connections return to the pool.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
