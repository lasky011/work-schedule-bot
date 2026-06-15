import sqlite3
import logging

from app_config import DATABASE_URL


try:
    import psycopg2
except ImportError:
    psycopg2 = None


USE_POSTGRES = bool(DATABASE_URL)
_pg_pool = None


class _PooledConn:
    """
    Прозрачная обёртка над psycopg2-соединением.

    conn.close() возвращает соединение в пул, а не закрывает его.
    """
    __slots__ = ("_conn", "_pool", "_closed")

    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool
        self._closed = False

    def cursor(self):
        return self._conn.cursor()

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        if self._closed:
            return

        self._closed = True
        try:
            self._conn.rollback()
        except Exception:
            pass

        self._pool.putconn(self._conn)

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def init_pg_pool():
    global _pg_pool

    if not USE_POSTGRES:
        return

    if psycopg2 is None:
        raise RuntimeError("psycopg2 не установлен, но DATABASE_URL задан")

    if _pg_pool is None:
        from psycopg2 import pool as _p

        _pg_pool = _p.ThreadedConnectionPool(
            minconn=1,
            maxconn=5,
            dsn=DATABASE_URL,
        )


def get_db_connection():
    if USE_POSTGRES:
        init_pg_pool()
        return _PooledConn(_pg_pool.getconn(), _pg_pool)

    # Локальный fallback пока оставлен для совместимости.
    # В production DATABASE_URL обязателен, поэтому эта ветка не используется.
    return sqlite3.connect("users.db")


def db_placeholder():
    return "%s" if USE_POSTGRES else "?"
