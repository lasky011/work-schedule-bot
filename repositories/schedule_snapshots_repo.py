"""Снимки графика пользователей для отслеживания изменений."""

import asyncio
import json

from db import USE_POSTGRES, get_db_connection, db_placeholder


def _get_snapshot_sync(user_id: int) -> str | None:
    meta = _get_snapshot_meta_sync(user_id)
    return meta[0] if meta else None


def _get_snapshot_meta_sync(user_id: int) -> tuple[str, object] | None:
    conn = get_db_connection()
    cursor = conn.cursor()
    ph = db_placeholder()
    cursor.execute(
        f"SELECT snapshot, updated_at FROM schedule_snapshots WHERE user_id={ph}",
        (user_id,),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return (row[0], row[1]) if row else None


def _save_snapshot_sync(user_id: int, snapshot: dict) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    ph = db_placeholder()
    payload = json.dumps(snapshot, ensure_ascii=False)
    if USE_POSTGRES:
        cursor.execute(
            f"""
            INSERT INTO schedule_snapshots (user_id, snapshot, updated_at)
            VALUES ({ph}, {ph}, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                snapshot = EXCLUDED.snapshot,
                updated_at = NOW()
            """,
            (user_id, payload),
        )
    else:
        cursor.execute(
            f"""
            INSERT OR REPLACE INTO schedule_snapshots (user_id, snapshot, updated_at)
            VALUES ({ph}, {ph}, datetime('now'))
            """,
            (user_id, payload),
        )
    conn.commit()
    cursor.close()
    conn.close()


def _delete_snapshot_sync(user_id: int) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    ph = db_placeholder()
    cursor.execute(f"DELETE FROM schedule_snapshots WHERE user_id={ph}", (user_id,))
    conn.commit()
    cursor.close()
    conn.close()


async def get_snapshot(user_id: int) -> str | None:
    return await asyncio.to_thread(_get_snapshot_sync, user_id)


async def get_snapshot_meta(user_id: int) -> tuple[str, object] | None:
    return await asyncio.to_thread(_get_snapshot_meta_sync, user_id)


async def save_snapshot(user_id: int, snapshot: dict) -> None:
    await asyncio.to_thread(_save_snapshot_sync, user_id, snapshot)


async def delete_snapshot(user_id: int) -> None:
    await asyncio.to_thread(_delete_snapshot_sync, user_id)
