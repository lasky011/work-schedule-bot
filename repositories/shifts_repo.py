import asyncio
import calendar
from datetime import date as _dt

from db import USE_POSTGRES, get_db_connection, db_placeholder


def _save_shift_sync(user_id, date, hours, shift_type=None, is_standard=True, note=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if USE_POSTGRES:
        cursor.execute(
            """
            INSERT INTO shifts (user_id, date, hours, shift_type, is_standard, note)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, date) DO UPDATE SET
                hours = EXCLUDED.hours,
                shift_type = EXCLUDED.shift_type,
                is_standard = EXCLUDED.is_standard,
                note = EXCLUDED.note
            """,
            (user_id, date, hours, shift_type, is_standard, note),
        )
    else:
        cursor.execute(
            "INSERT OR REPLACE INTO shifts (user_id, date, hours, shift_type, is_standard, note) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, date, hours, shift_type, is_standard, note),
        )
    conn.commit()
    cursor.close()
    conn.close()


async def save_shift(user_id, date, hours, shift_type=None, is_standard=True, note=None):
    await asyncio.to_thread(_save_shift_sync, user_id, date, hours, shift_type, is_standard, note)


def _get_shifts_for_month_sync(user_id, year, month):
    conn = get_db_connection()
    cursor = conn.cursor()
    if USE_POSTGRES:
        # date range вместо EXTRACT — задействует индекс UNIQUE(user_id, date)
        from datetime import date as _dt
        _, last = calendar.monthrange(year, month)
        cursor.execute(
            "SELECT date, hours, shift_type, is_standard, note FROM shifts "
            "WHERE user_id=%s AND date >= %s AND date <= %s ORDER BY date",
            (user_id, _dt(year, month, 1), _dt(year, month, last)),
        )
    else:
        cursor.execute(
            "SELECT date, hours, shift_type, is_standard, note FROM shifts "
            "WHERE user_id=? AND strftime('%Y', date)=? AND strftime('%m', date)=? ORDER BY date",
            (user_id, str(year), str(month).zfill(2)),
        )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


async def get_shifts_for_month(user_id, year, month):
    return await asyncio.to_thread(_get_shifts_for_month_sync, user_id, year, month)


def _delete_shift_sync(user_id, date):
    conn = get_db_connection()
    cursor = conn.cursor()
    ph = db_placeholder()
    cursor.execute(f"DELETE FROM shifts WHERE user_id={ph} AND date={ph}", (user_id, date))
    deleted = cursor.rowcount > 0
    conn.commit()
    cursor.close()
    conn.close()
    return deleted


async def delete_shift(user_id, date):
    return await asyncio.to_thread(_delete_shift_sync, user_id, date)


def _get_shift_for_date_sync(user_id, date):
    conn = get_db_connection()
    cursor = conn.cursor()
    ph = db_placeholder()
    cursor.execute(
        f"SELECT date, hours, shift_type, is_standard, note FROM shifts WHERE user_id={ph} AND date={ph}",
        (user_id, date),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


async def get_shift_for_date(user_id, date):
    return await asyncio.to_thread(_get_shift_for_date_sync, user_id, date)
