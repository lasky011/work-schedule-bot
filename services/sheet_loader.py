"""Загрузка и кэширование Google Sheets по gid."""

import asyncio
import logging

from app_config import now_local
from departments_manager import refresh_departments
from services import schedule_service as schedule
from services.sheet_periods_service import SHEET_GID_MAP
from sheets_client import cache_locks, cached_df, cached_time, download_sheet

CACHE_REFRESH_SECONDS = 1800


def oldest_cache_age_seconds() -> int | None:
    if not cached_time:
        return None
    now = now_local()
    try:
        return max(int((now - ts).total_seconds()) for ts in cached_time.values())
    except Exception:
        return None


async def _cache_gid(gid: int) -> None:
    if gid not in cache_locks:
        cache_locks[gid] = asyncio.Lock()

    async with cache_locks[gid]:
        df = await download_sheet(gid)
        cached_df[gid] = df
        cached_time[gid] = now_local()


async def load_sheet(day, month=None, year=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year

    gid = schedule.get_gid_for_day_month(day, month, year)
    if gid is None:
        raise ValueError(
            f"Нет GID для {year}-{month}, день {day}. "
            "Добавь период через /add_period."
        )

    if gid in cached_df and gid in cached_time:
        if (now_local() - cached_time[gid]).total_seconds() < 60:
            return cached_df[gid]

    await _cache_gid(gid)
    return cached_df[gid]


async def load_all_sheet_gids() -> tuple[int, int, list[str]]:
    """Загружает все уникальные gid из SHEET_GID_MAP в локальный кэш."""
    gids = sorted({int(gid) for gid in SHEET_GID_MAP.values()})
    if not gids:
        return 0, 0, []

    loaded = 0
    errors: list[str] = []
    for gid in gids:
        try:
            await _cache_gid(gid)
            loaded += 1
        except Exception as e:
            errors.append(f"gid={gid}: {e}")

    if loaded:
        await refresh_departments(force=True)
    return loaded, len(gids) - loaded, errors


async def load_full_sheet():
    loaded, failed, errors = await load_all_sheet_gids()
    if loaded == 0:
        if errors:
            logging.warning("Не удалось загрузить листы при старте: %s", "; ".join(errors[:3]))
        else:
            logging.warning("Нет доступных листов при старте — бот запустится без кэша.")
        return None
    if failed:
        logging.warning(
            "Загружено %s gid, ошибок: %s (%s)",
            loaded,
            failed,
            "; ".join(errors[:3]),
        )
    return None
