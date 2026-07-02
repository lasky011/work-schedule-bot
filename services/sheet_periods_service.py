"""Кэш периодов Google Sheets: загрузка из БД с fallback на constants."""

import asyncio
import logging

from constants import SHEET_GID_MAP as FALLBACK_SHEET_GID_MAP
from repositories.sheet_periods_repo import fetch_all, upsert

# Общий dict мутируется in-place — фильтры и импорты не ломаются.
SHEET_GID_MAP: dict[tuple[int, int, int], str] = dict(FALLBACK_SHEET_GID_MAP)


def _apply_rows(rows: list[tuple[int, int, int, str]]) -> int:
    SHEET_GID_MAP.clear()
    for year, month, start_day, gid in rows:
        SHEET_GID_MAP[(year, month, start_day)] = gid
    return len(SHEET_GID_MAP)


def _restore_fallback() -> int:
    SHEET_GID_MAP.clear()
    SHEET_GID_MAP.update(FALLBACK_SHEET_GID_MAP)
    return len(SHEET_GID_MAP)


def load_from_db_sync() -> int:
    from db import USE_POSTGRES
    from repositories.sheet_periods_repo import _fetch_all_sync

    if not USE_POSTGRES:
        return _restore_fallback()

    try:
        conn_rows = _fetch_all_sync()
    except Exception as e:
        logging.warning(
            "sheet_periods: не удалось загрузить из БД, оставляем текущий кэш: %s",
            e,
        )
        if not SHEET_GID_MAP:
            return _restore_fallback()
        return len(SHEET_GID_MAP)

    if not conn_rows:
        logging.warning(
            "sheet_periods: таблица пуста, используем fallback из constants.py"
        )
        return _restore_fallback()

    count = _apply_rows(conn_rows)
    logging.info("sheet_periods: загружено %s периодов из БД", count)
    return count


async def reload_from_db() -> int:
    return await asyncio.to_thread(load_from_db_sync)


async def add_period(year: int, month: int, start_day: int, gid: str) -> int:
    await upsert(year, month, start_day, gid)
    return await reload_from_db()
