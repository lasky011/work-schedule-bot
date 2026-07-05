import asyncio
import logging

from db import USE_POSTGRES, get_db_connection

SHEET_CACHE_VERSION_KEY = "sheet_cache_version"


def _get_int_sync(key: str, default: int = 0) -> int:
    if not USE_POSTGRES:
        return default

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT value FROM bot_state WHERE key = %s", (key,))
        row = cursor.fetchone()
        if not row:
            return default
        return int(row[0])
    except Exception:
        return default
    finally:
        cursor.close()
        conn.close()


def _bump_int_sync(key: str) -> int:
    if not USE_POSTGRES:
        return 0

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO bot_state (key, value, updated_at)
            VALUES (%s, '1', NOW())
            ON CONFLICT (key) DO UPDATE
            SET value = (bot_state.value::bigint + 1)::text,
                updated_at = NOW()
            RETURNING value
            """,
            (key,),
        )
        row = cursor.fetchone()
        conn.commit()
        return int(row[0]) if row else 0
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


async def get_int(key: str, default: int = 0) -> int:
    return await asyncio.to_thread(_get_int_sync, key, default)


async def bump_int(key: str) -> int:
    return await asyncio.to_thread(_bump_int_sync, key)


async def bump_sheet_cache_version() -> int:
    try:
        return await bump_int(SHEET_CACHE_VERSION_KEY)
    except Exception as e:
        logging.warning("bot_state bump_sheet_cache_version failed: %s", e)
        return 0
