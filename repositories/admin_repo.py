import asyncio
import calendar
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


def _broadcast_recipients_sync(audience: str = "notify") -> list[tuple[int, str | None]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    queries = {
        "all": "SELECT user_id, name FROM users WHERE name IS NOT NULL",
        "notify": "SELECT user_id, name FROM users WHERE notify=1 AND name IS NOT NULL",
        "track": "SELECT user_id, name FROM users WHERE track_hours=1 AND name IS NOT NULL",
        "hours": "SELECT user_id, name FROM users WHERE notify_hours=1 AND name IS NOT NULL",
    }
    sql = queries.get(audience, queries["notify"])
    try:
        cursor.execute(sql)
        return [(row[0], row[1]) for row in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()


async def get_dashboard_stats() -> dict:
    return await asyncio.to_thread(_get_dashboard_stats_sync)


async def list_users() -> list[tuple]:
    return await asyncio.to_thread(_list_users_sync)


async def get_broadcast_recipients(audience: str = "notify") -> list[tuple[int, str | None]]:
    return await asyncio.to_thread(_broadcast_recipients_sync, audience)


def _shift_stats_sync(year: int, month: int) -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        _, last_day = calendar.monthrange(year, month)
        month_start = date(year, month, 1)
        month_end = date(year, month, last_day)

        cursor.execute(
            """
            SELECT COALESCE(u.name, '—'), COALESCE(u.role, '—'),
                   COUNT(s.id), COALESCE(SUM(s.hours), 0)
            FROM shifts s
            LEFT JOIN users u ON u.user_id = s.user_id
            WHERE s.date >= %s AND s.date <= %s
            GROUP BY u.user_id, u.name, u.role
            ORDER BY SUM(s.hours) DESC, u.name
            """,
            (month_start, month_end),
        )
        rows = cursor.fetchall()

        cursor.execute(
            "SELECT COUNT(*), COALESCE(SUM(hours), 0) FROM shifts "
            "WHERE date >= %s AND date <= %s",
            (month_start, month_end),
        )
        total_shifts, total_hours = cursor.fetchone()

        return {
            "year": year,
            "month": month,
            "rows": rows,
            "total_shifts": int(total_shifts or 0),
            "total_hours": float(total_hours or 0),
            "people_count": len(rows),
        }
    finally:
        cursor.close()
        conn.close()


async def get_shift_stats(year: int, month: int) -> dict:
    return await asyncio.to_thread(_shift_stats_sync, year, month)
