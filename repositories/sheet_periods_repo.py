import asyncio
import logging

from db import USE_POSTGRES, get_db_connection


def _fetch_all_sync() -> list[tuple[int, int, int, str]]:
    if not USE_POSTGRES:
        return []

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT year, month, start_day, gid "
            "FROM sheet_periods "
            "ORDER BY year, month, start_day"
        )
        return [(row[0], row[1], row[2], str(row[3])) for row in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()


def _upsert_sync(year: int, month: int, start_day: int, gid: str) -> None:
    if not USE_POSTGRES:
        raise RuntimeError("sheet_periods доступны только с PostgreSQL")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO sheet_periods (year, month, start_day, gid)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (year, month, start_day)
            DO UPDATE SET gid = EXCLUDED.gid
            """,
            (year, month, start_day, gid),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


async def fetch_all() -> list[tuple[int, int, int, str]]:
    try:
        return await asyncio.to_thread(_fetch_all_sync)
    except Exception as e:
        logging.warning("sheet_periods_repo.fetch_all failed: %s", e)
        return []


async def upsert(year: int, month: int, start_day: int, gid: str) -> None:
    await asyncio.to_thread(_upsert_sync, year, month, start_day, gid)


def _delete_sync(year: int, month: int, start_day: int) -> bool:
    if not USE_POSTGRES:
        raise RuntimeError("sheet_periods доступны только с PostgreSQL")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM sheet_periods WHERE year=%s AND month=%s AND start_day=%s",
            (year, month, start_day),
        )
        deleted = cursor.rowcount > 0
        conn.commit()
        return deleted
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


async def delete_period(year: int, month: int, start_day: int) -> bool:
    return await asyncio.to_thread(_delete_sync, year, month, start_day)
