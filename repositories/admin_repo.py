import asyncio
import calendar
from datetime import date

from app_config import now_local
from db import get_db_connection


def _get_dashboard_stats_sync() -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        today = now_local().date()
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


def _search_users_sync(query: str, limit: int = 8) -> list[tuple]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        q = query.strip()
        if q.isdigit():
            cursor.execute(
                """
                SELECT user_id, name, role, notify, notify_time, notify_hours, track_hours
                FROM users WHERE user_id = %s
                """,
                (int(q),),
            )
        else:
            cursor.execute(
                """
                SELECT user_id, name, role, notify, notify_time, notify_hours, track_hours
                FROM users
                WHERE name ILIKE %s
                ORDER BY name NULLS LAST, user_id
                LIMIT %s
                """,
                (f"%{q}%", limit),
            )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def _get_recent_shifts_sync(user_id: int, limit: int = 5) -> list[tuple]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT date, hours FROM shifts
            WHERE user_id = %s
            ORDER BY date DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def _watch_monitor_stats_sync() -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE name IS NOT NULL AND name != ''"
        )
        registered = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM schedule_snapshots")
        snapshots = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT u.user_id, u.name
            FROM users u
            LEFT JOIN schedule_snapshots s ON s.user_id = u.user_id
            WHERE u.name IS NOT NULL AND u.name != '' AND s.user_id IS NULL
            ORDER BY u.name
            LIMIT 15
            """
        )
        missing = cursor.fetchall()

        cursor.execute("SELECT COUNT(*) FROM users WHERE track_hours = 1 AND name IS NOT NULL")
        track_hours = cursor.fetchone()[0]

        return {
            "registered": registered,
            "snapshots": snapshots,
            "missing_snapshots": max(0, registered - snapshots),
            "missing_users": missing,
            "track_hours": track_hours,
        }
    finally:
        cursor.close()
        conn.close()


def _track_hours_users_sync() -> list[tuple[int, str, str | None]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT user_id, name, role
            FROM users
            WHERE track_hours = 1 AND name IS NOT NULL AND name != ''
            ORDER BY name
            """
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


async def search_users(query: str, limit: int = 8) -> list[tuple]:
    return await asyncio.to_thread(_search_users_sync, query, limit)


async def get_user_recent_shifts(user_id: int, limit: int = 5) -> list[tuple]:
    return await asyncio.to_thread(_get_recent_shifts_sync, user_id, limit)


async def get_watch_monitor_stats() -> dict:
    return await asyncio.to_thread(_watch_monitor_stats_sync)


async def list_track_hours_users() -> list[tuple[int, str, str | None]]:
    return await asyncio.to_thread(_track_hours_users_sync)
