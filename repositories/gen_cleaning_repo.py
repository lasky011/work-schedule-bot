"""Ручные дни ген уборки и факт отправки напоминания."""

import asyncio
import logging
from datetime import date

from db import USE_POSTGRES, get_db_connection


def ensure_schema_sync() -> None:
    if not USE_POSTGRES:
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS gen_cleaning_month_overrides (
                year INT NOT NULL CHECK (year BETWEEN 2000 AND 2100),
                month INT NOT NULL CHECK (month BETWEEN 1 AND 12),
                days INT[] NOT NULL DEFAULT '{}',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (year, month)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS gen_cleaning_notify_sent (
                cleaning_day DATE PRIMARY KEY,
                sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def _fetch_overrides_sync() -> list[tuple[int, int, list[int]]]:
    if not USE_POSTGRES:
        return []

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT year, month, days FROM gen_cleaning_month_overrides "
            "ORDER BY year, month"
        )
        rows = []
        for year, month, days in cursor.fetchall():
            raw = days or []
            parsed = [int(d) for d in raw if d is not None]
            rows.append((int(year), int(month), parsed))
        return rows
    except Exception as e:
        logging.warning("gen_cleaning_repo.fetch_overrides failed: %s", e)
        return []
    finally:
        cursor.close()
        conn.close()


def _upsert_month_sync(year: int, month: int, days: list[int]) -> None:
    if not USE_POSTGRES:
        raise RuntimeError("ген уборка в админке доступна только с PostgreSQL")

    unique_days = sorted({int(d) for d in days if 1 <= int(d) <= 31})
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO gen_cleaning_month_overrides (year, month, days)
            VALUES (%s, %s, %s)
            ON CONFLICT (year, month)
            DO UPDATE SET days = EXCLUDED.days, updated_at = NOW()
            """,
            (year, month, unique_days),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def _delete_month_sync(year: int, month: int) -> bool:
    if not USE_POSTGRES:
        return False

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM gen_cleaning_month_overrides WHERE year=%s AND month=%s",
            (year, month),
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


def _try_claim_notify_sync(cleaning_day: date) -> bool:
    """True — этот процесс должен разослать напоминание."""
    if not USE_POSTGRES:
        return True

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO gen_cleaning_notify_sent (cleaning_day)
            VALUES (%s)
            ON CONFLICT (cleaning_day) DO NOTHING
            RETURNING cleaning_day
            """,
            (cleaning_day,),
        )
        claimed = cursor.fetchone() is not None
        conn.commit()
        return claimed
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def _clear_notify_sync(cleaning_day: date) -> None:
    if not USE_POSTGRES:
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM gen_cleaning_notify_sent WHERE cleaning_day=%s",
            (cleaning_day,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


async def fetch_overrides() -> list[tuple[int, int, list[int]]]:
    return await asyncio.to_thread(_fetch_overrides_sync)


async def upsert_month(year: int, month: int, days: list[int]) -> None:
    await asyncio.to_thread(_upsert_month_sync, year, month, days)


async def delete_month(year: int, month: int) -> bool:
    return await asyncio.to_thread(_delete_month_sync, year, month)


async def try_claim_notify(cleaning_day: date) -> bool:
    return await asyncio.to_thread(_try_claim_notify_sync, cleaning_day)


async def clear_notify(cleaning_day: date) -> None:
    await asyncio.to_thread(_clear_notify_sync, cleaning_day)
