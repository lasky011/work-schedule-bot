"""Загрузка и кэширование Google Sheets по gid."""

import asyncio
import logging

from app_config import now_local
from departments_manager import refresh_departments
from services import schedule_service as schedule
from sheets_client import cache_locks, cached_df, cached_time, download_sheet


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

    if gid not in cache_locks:
        cache_locks[gid] = asyncio.Lock()

    async with cache_locks[gid]:
        now_time = now_local()
        if gid in cached_df and gid in cached_time:
            if (now_time - cached_time[gid]).total_seconds() < 60:
                return cached_df[gid]

        df = await download_sheet(gid)
        cached_df[gid] = df
        cached_time[gid] = now_time
        return cached_df[gid]


async def load_full_sheet():
    dfs = []
    for day in [1, 16]:
        try:
            dfs.append(await load_sheet(day))
        except (ValueError, ConnectionError):
            pass
    if not dfs:
        logging.warning("Нет доступных листов при старте — бот запустится без кэша.")
        return None
    await refresh_departments(force=True)
    return None
