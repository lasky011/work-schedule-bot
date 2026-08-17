"""Pending sheet-name renames that need admin confirmation."""

from __future__ import annotations

import asyncio
import logging

from db import USE_POSTGRES, db_placeholder, get_db_connection


def ensure_schema() -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if USE_POSTGRES:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS name_rename_requests (
                id            SERIAL PRIMARY KEY,
                user_id       BIGINT NOT NULL,
                old_name      TEXT NOT NULL,
                new_name      TEXT NOT NULL,
                role          TEXT,
                status        TEXT NOT NULL DEFAULT 'pending',
                created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                resolved_at   TIMESTAMPTZ,
                resolved_by   BIGINT
            )
            """)
            cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS name_rename_requests_pending_uidx
                ON name_rename_requests (user_id, old_name, new_name)
                WHERE status = 'pending'
            """)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS person_name_aliases (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT NOT NULL,
                alias       TEXT NOT NULL,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (user_id, alias)
            )
            """)
            cursor.execute("""
            CREATE INDEX IF NOT EXISTS person_name_aliases_alias_idx
                ON person_name_aliases (alias)
            """)
        else:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS name_rename_requests (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                old_name      TEXT NOT NULL,
                new_name      TEXT NOT NULL,
                role          TEXT,
                status        TEXT NOT NULL DEFAULT 'pending',
                created_at    TEXT DEFAULT (datetime('now')),
                resolved_at   TEXT,
                resolved_by   INTEGER
            )
            """)
            cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS name_rename_requests_pending_uidx
                ON name_rename_requests (user_id, old_name, new_name)
                WHERE status = 'pending'
            """)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS person_name_aliases (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                alias       TEXT NOT NULL,
                created_at  TEXT DEFAULT (datetime('now')),
                UNIQUE (user_id, alias)
            )
            """)
            cursor.execute("""
            CREATE INDEX IF NOT EXISTS person_name_aliases_alias_idx
                ON person_name_aliases (alias)
            """)
        conn.commit()
    except Exception:
        conn.rollback()
        logging.exception("name_rename ensure_schema failed")
        raise
    finally:
        cursor.close()
        conn.close()


def _create_pending_sync(
    user_id: int,
    old_name: str,
    new_name: str,
    role: str | None,
) -> int | None:
    """Insert pending rename. Returns id, or None if already pending/rejected recently."""
    conn = get_db_connection()
    cursor = conn.cursor()
    ph = db_placeholder()
    try:
        # Already pending for this triple → reuse id.
        cursor.execute(
            f"""
            SELECT id FROM name_rename_requests
            WHERE user_id = {ph} AND old_name = {ph} AND new_name = {ph}
              AND status = 'pending'
            LIMIT 1
            """,
            (user_id, old_name, new_name),
        )
        row = cursor.fetchone()
        if row:
            return int(row[0])

        # Rejected same pair → do not re-ask.
        cursor.execute(
            f"""
            SELECT id FROM name_rename_requests
            WHERE user_id = {ph} AND old_name = {ph} AND new_name = {ph}
              AND status = 'rejected'
            LIMIT 1
            """,
            (user_id, old_name, new_name),
        )
        if cursor.fetchone():
            return None

        if USE_POSTGRES:
            cursor.execute(
                """
                INSERT INTO name_rename_requests (user_id, old_name, new_name, role, status)
                VALUES (%s, %s, %s, %s, 'pending')
                RETURNING id
                """,
                (user_id, old_name, new_name, role),
            )
            new_id = int(cursor.fetchone()[0])
        else:
            cursor.execute(
                """
                INSERT INTO name_rename_requests (user_id, old_name, new_name, role, status)
                VALUES (?, ?, ?, ?, 'pending')
                """,
                (user_id, old_name, new_name, role),
            )
            new_id = int(cursor.lastrowid)

        conn.commit()
        return new_id
    except Exception:
        conn.rollback()
        logging.exception(
            "name_rename create_pending failed user_id=%s %r→%r",
            user_id, old_name, new_name,
        )
        return None
    finally:
        cursor.close()
        conn.close()


def _get_sync(request_id: int) -> tuple | None:
    conn = get_db_connection()
    cursor = conn.cursor()
    ph = db_placeholder()
    try:
        cursor.execute(
            f"""
            SELECT id, user_id, old_name, new_name, role, status
            FROM name_rename_requests
            WHERE id = {ph}
            """,
            (request_id,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def _resolve_sync(request_id: int, status: str, resolved_by: int) -> bool:
    if status not in ("confirmed", "rejected"):
        return False
    conn = get_db_connection()
    cursor = conn.cursor()
    ph = db_placeholder()
    try:
        if USE_POSTGRES:
            cursor.execute(
                f"""
                UPDATE name_rename_requests
                SET status = {ph}, resolved_at = NOW(), resolved_by = {ph}
                WHERE id = {ph} AND status = 'pending'
                """,
                (status, resolved_by, request_id),
            )
        else:
            cursor.execute(
                f"""
                UPDATE name_rename_requests
                SET status = {ph},
                    resolved_at = datetime('now'),
                    resolved_by = {ph}
                WHERE id = {ph} AND status = 'pending'
                """,
                (status, resolved_by, request_id),
            )
        ok = cursor.rowcount > 0
        conn.commit()
        return ok
    except Exception:
        conn.rollback()
        logging.exception("name_rename resolve failed id=%s", request_id)
        return False
    finally:
        cursor.close()
        conn.close()


def _list_pending_sync(limit: int = 50) -> list[tuple]:
    conn = get_db_connection()
    cursor = conn.cursor()
    ph = db_placeholder()
    try:
        cursor.execute(
            f"""
            SELECT id, user_id, old_name, new_name, role, created_at
            FROM name_rename_requests
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT {ph}
            """,
            (limit,),
        )
        return cursor.fetchall() or []
    finally:
        cursor.close()
        conn.close()


async def create_pending(
    user_id: int, old_name: str, new_name: str, role: str | None = None,
) -> int | None:
    return await asyncio.to_thread(
        _create_pending_sync, user_id, old_name, new_name, role,
    )


async def get_request(request_id: int) -> tuple | None:
    return await asyncio.to_thread(_get_sync, request_id)


async def resolve_request(request_id: int, status: str, resolved_by: int) -> bool:
    return await asyncio.to_thread(_resolve_sync, request_id, status, resolved_by)


async def list_pending(limit: int = 50) -> list[tuple]:
    return await asyncio.to_thread(_list_pending_sync, limit)


def _add_alias_sync(user_id: int, alias: str) -> None:
    name = (alias or "").replace("\xa0", " ").strip()
    if not user_id or not name:
        return
    try:
        conn = get_db_connection()
    except Exception:
        logging.exception("add_alias: no db user_id=%s alias=%r", user_id, name)
        return
    cursor = conn.cursor()
    ph = db_placeholder()
    try:
        if USE_POSTGRES:
            cursor.execute(
                f"""
                INSERT INTO person_name_aliases (user_id, alias)
                VALUES ({ph}, {ph})
                ON CONFLICT (user_id, alias) DO NOTHING
                """,
                (user_id, name),
            )
        else:
            cursor.execute(
                f"""
                INSERT OR IGNORE INTO person_name_aliases (user_id, alias)
                VALUES ({ph}, {ph})
                """,
                (user_id, name),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        logging.exception("add_alias failed user_id=%s alias=%r", user_id, name)
    finally:
        cursor.close()
        conn.close()


def _list_aliases_sync(user_id: int) -> list[str]:
    try:
        conn = get_db_connection()
    except Exception:
        logging.exception("list_aliases: no db user_id=%s", user_id)
        return []
    cursor = conn.cursor()
    ph = db_placeholder()
    try:
        cursor.execute(
            f"SELECT alias FROM person_name_aliases WHERE user_id = {ph} ORDER BY alias",
            (user_id,),
        )
        return [str(r[0]) for r in (cursor.fetchall() or []) if r and r[0]]
    except Exception as e:
        logging.warning("list_aliases failed user_id=%s: %s", user_id, e)
        return []
    finally:
        cursor.close()
        conn.close()


async def add_alias(user_id: int, alias: str) -> None:
    await asyncio.to_thread(_add_alias_sync, user_id, alias)


async def list_aliases(user_id: int) -> list[str]:
    return await asyncio.to_thread(_list_aliases_sync, user_id)


async def remember_rename_aliases(user_id: int, *names: str) -> None:
    """Keep all historical sheet names for schedule lookup across periods."""
    for name in names:
        await add_alias(user_id, name)
