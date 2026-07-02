"""Кэш периодов Google Sheets: загрузка из БД с fallback на constants."""

import asyncio
import logging

from constants import SHEET_GID_MAP as FALLBACK_SHEET_GID_MAP
from repositories.sheet_periods_repo import delete_period as repo_delete_period, fetch_all, upsert

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


def load_from_db_sync(*, quiet: bool = False) -> int:
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
        if quiet and SHEET_GID_MAP:
            return len(SHEET_GID_MAP)
        logging.warning(
            "sheet_periods: таблица пуста, используем fallback из constants.py"
        )
        return _restore_fallback()

    before = dict(SHEET_GID_MAP)
    count = _apply_rows(conn_rows)
    if not quiet or before != SHEET_GID_MAP:
        if before != SHEET_GID_MAP:
            logging.info("sheet_periods: синхронизировано с БД (%s периодов)", count)
        else:
            logging.info("sheet_periods: загружено %s периодов из БД", count)
    return count


async def reload_from_db(*, quiet: bool = False) -> int:
    return await asyncio.to_thread(load_from_db_sync, quiet=quiet)


async def sync_from_db() -> bool:
    """Перечитывает периоды из БД. True — если кэш изменился."""
    before = dict(SHEET_GID_MAP)
    await reload_from_db(quiet=True)
    return dict(SHEET_GID_MAP) != before


async def add_period(year: int, month: int, start_day: int, gid: str) -> int:
    await upsert(year, month, start_day, gid)
    return await reload_from_db()


async def remove_period(year: int, month: int, start_day: int) -> int:
    deleted = await repo_delete_period(year, month, start_day)
    if not deleted:
        raise ValueError("Период не найден в БД")
    return await reload_from_db()
