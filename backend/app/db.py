import logging
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Idle reclaims connections above min_size. Lifetime recycles every connection,
# including the one the pool keeps warm. Both values are seconds.
_MAX_IDLE_SECONDS = 5 * 60
_MAX_LIFETIME_SECONDS = 30 * 60

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    if _pool is None or _pool.closed:
        raise RuntimeError("Database pool is not open")
    return _pool


def open_pool() -> None:
    global _pool
    if _pool is not None and not _pool.closed:
        return
    pool = ConnectionPool(
        get_settings().database_url,
        kwargs={"row_factory": dict_row},
        min_size=1,
        max_size=10,
        open=False,
        max_idle=_MAX_IDLE_SECONDS,
        max_lifetime=_MAX_LIFETIME_SECONDS,
    )
    try:
        pool.open(wait=True)
    except Exception:
        pool.close()
        raise
    _pool = pool


def close_pool() -> None:
    if _pool is not None:
        _pool.close()


@contextmanager
def transaction() -> Iterator[psycopg.Connection]:
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except BaseException:
        try:
            conn.rollback()
        except Exception as rollback_error:
            logger.warning(
                "database rollback failed type=%s message=%s",
                type(rollback_error).__name__,
                rollback_error,
            )
        raise
    finally:
        pool.putconn(conn)


def query_one(sql: str, params: tuple | dict | None = None) -> dict | None:
    with transaction() as conn:
        return conn.execute(sql, params).fetchone()


def query_all(sql: str, params: tuple | dict | None = None) -> list[dict]:
    with transaction() as conn:
        return list(conn.execute(sql, params).fetchall())


def execute(sql: str, params: tuple | dict | None = None) -> int:
    with transaction() as conn:
        return conn.execute(sql, params).rowcount


def database_error(exc: BaseException, *, conflict: str = "Conflict") -> HTTPException:
    sqlstate = getattr(exc, "sqlstate", None)
    if sqlstate == "23505":
        return HTTPException(status_code=409, detail=conflict)
    if sqlstate == "23503":
        return HTTPException(status_code=404, detail="Not found")
    if sqlstate == "P0002":
        return HTTPException(status_code=404, detail="Not found")
    if sqlstate == "23514":
        return HTTPException(status_code=422, detail="Invalid value")
    logger.error(
        "database error type=%s sqlstate=%s message=%s",
        type(exc).__name__,
        sqlstate,
        exc,
    )
    return HTTPException(status_code=500, detail="Database request failed")
