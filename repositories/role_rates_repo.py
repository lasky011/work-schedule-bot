import asyncio
import logging

from db import USE_POSTGRES, get_db_connection


def _fetch_all_sync() -> list[tuple[str, int]]:
    if not USE_POSTGRES:
        return []

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT role_key, rate FROM role_rates ORDER BY role_key"
        )
        return [(row[0], int(row[1])) for row in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()


def _upsert_sync(role_key: str, rate: int) -> None:
    if not USE_POSTGRES:
        raise RuntimeError("role_rates доступны только с PostgreSQL")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO role_rates (role_key, rate)
            VALUES (%s, %s)
            ON CONFLICT (role_key)
            DO UPDATE SET rate = EXCLUDED.rate, updated_at = NOW()
            """,
            (role_key, rate),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


async def fetch_all() -> list[tuple[str, int]]:
    try:
        return await asyncio.to_thread(_fetch_all_sync)
    except Exception as e:
        logging.warning("role_rates_repo.fetch_all failed: %s", e)
        return []


async def upsert(role_key: str, rate: int) -> None:
    await asyncio.to_thread(_upsert_sync, role_key, rate)
