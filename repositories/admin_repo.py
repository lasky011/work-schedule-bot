import asyncio
from datetime import date

from db import get_db_connection


def _get_dashboard_stats_sync() -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        today = date.today()
        month_start = today.replace(day=1)

        cursor.execute("SELECT COUNT(*) FROM users")
        users_total = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE name IS NOT NULL")
        users_named = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE notify=1")
        notify_shift = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE notify_hours=1")
        notify_hours = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE track_hours=1")
        track_hours = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM shifts")
        shifts_total = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM shifts WHERE date >= %s",
            (month_start,),
        )
        shifts_month = cursor.fetchone()[0]

        return {
            "users_total": users_total,
            "users_named": users_named,
            "notify_shift": notify_shift,
            "notify_hours": notify_hours,
            "track_hours": track_hours,
            "shifts_total": shifts_total,
            "shifts_month": shifts_month,
            "month": today.month,
            "year": today.year,
        }
    finally:
        cursor.close()
        conn.close()


def _list_users_sync() -> list[tuple]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT user_id, name, role, notify, notify_time, notify_hours, track_hours
            FROM users
            ORDER BY name NULLS LAST, user_id
            """
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def _broadcast_recipients_sync(notify_shift: bool = True) -> list[tuple[int, str | None]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if notify_shift:
            cursor.execute(
                "SELECT user_id, name FROM users "
                "WHERE notify=1 AND name IS NOT NULL"
            )
        else:
            cursor.execute(
                "SELECT user_id, name FROM users WHERE name IS NOT NULL"
            )
        return [(row[0], row[1]) for row in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()


async def get_dashboard_stats() -> dict:
    return await asyncio.to_thread(_get_dashboard_stats_sync)


async def list_users() -> list[tuple]:
    return await asyncio.to_thread(_list_users_sync)


async def get_broadcast_recipients(notify_shift: bool = True) -> list[tuple[int, str | None]]:
    return await asyncio.to_thread(_broadcast_recipients_sync, notify_shift)
