"""Сигнал admin→main: когда админ обновил листы, main подхватывает кэш."""

import logging

from repositories.bot_state_repo import SHEET_CACHE_VERSION_KEY, get_int
from services.sheet_loader import CACHE_REFRESH_SECONDS, load_all_sheet_gids, oldest_cache_age_seconds
from services.sheet_periods_service import reload_from_db

_last_applied_version = 0


async def bump_sheet_cache_signal() -> int:
    from repositories.bot_state_repo import bump_sheet_cache_version

    version = await bump_sheet_cache_version()
    if version:
        logging.info("sheet cache signal bumped: v%s", version)
    return version


async def pending_sheet_cache_signal() -> bool:
    global _last_applied_version
    current = await get_int(SHEET_CACHE_VERSION_KEY, default=0)
    return current > _last_applied_version


async def apply_pending_sheet_cache_signal() -> bool:
    """Перечитывает периоды и листы, если админ поднял сигнал."""
    global _last_applied_version

    current = await get_int(SHEET_CACHE_VERSION_KEY, default=0)
    if current <= _last_applied_version:
        return False

    try:
        await reload_from_db(quiet=True)
        loaded, failed, errors = await load_all_sheet_gids()
        _last_applied_version = current
        logging.info(
            "sheet cache signal applied: v%s loaded=%s failed=%s",
            current,
            loaded,
            failed,
        )
        if failed and errors:
            logging.warning("sheet cache signal errors: %s", "; ".join(errors[:3]))
        return True
    except Exception:
        logging.exception("sheet cache signal apply failed (v%s)", current)
        return False


async def maybe_refresh_sheet_cache() -> None:
    """Плановый refresh + реакция на сигнал из admin-бота."""
    from services.rates_service import apply_pending_rates_signal

    if await apply_pending_rates_signal():
        pass

    if await apply_pending_sheet_cache_signal():
        return

    age = oldest_cache_age_seconds()
    if age is None or age < CACHE_REFRESH_SECONDS:
        return

    try:
        loaded, failed, errors = await load_all_sheet_gids()
        logging.info(
            "sheet cache refresh: age=%ss loaded=%s failed=%s",
            age,
            loaded,
            failed,
        )
        if failed and errors:
            logging.warning("sheet cache refresh errors: %s", "; ".join(errors[:3]))
    except Exception:
        logging.exception("sheet cache refresh failed")
