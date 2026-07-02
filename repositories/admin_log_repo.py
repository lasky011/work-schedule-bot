import asyncio
import logging

from db import USE_POSTGRES, get_db_connection


def _insert_sync(admin_user_id: int, action: str, details: str | None = None) -> None:
    if not USE_POSTGRES:
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO admin_log (admin_user_id, action, details) VALUES (%s, %s, %s)",
            (admin_user_id, action, details),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def _list_recent_sync(limit: int = 30) -> list[tuple]:
    if not USE_POSTGRES:
        return []

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT created_at, admin_user_id, action, details
            FROM admin_log
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


async def insert_log(admin_user_id: int, action: str, details: str | None = None) -> None:
    await asyncio.to_thread(_insert_sync, admin_user_id, action, details)


async def list_recent_logs(limit: int = 30) -> list[tuple]:
    return await asyncio.to_thread(_list_recent_sync, limit)


async def record_action(admin_user_id: int, action: str, details: str | None = None) -> None:
    try:
        await insert_log(admin_user_id, action, details)
    except Exception as e:
        logging.warning("admin_log write failed: %s", e)
