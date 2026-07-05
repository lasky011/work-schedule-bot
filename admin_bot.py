"""Точка входа admin-бота (@graf_tng_adminbot)."""

import asyncio
import logging
import traceback

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app_config import (
    SHEET_PERIODS_REFRESH_SECONDS,
    now_local,
    validate_admin_env,
)
from db import init_pg_pool
from departments_manager import configure_departments_manager
from keyboards import configure_keyboard_context
from routers.admin import configure_admin_router, router as admin_router
from schedule_utils import configure_schedule_utils
from services import schedule_service as schedule
from services.admin_alerts_service import run_health_alerts
from services.admin_health_service import CACHE_REFRESH_SECONDS, oldest_cache_age_seconds
from services.sheet_loader import load_all_sheet_gids, load_full_sheet
from services.sheet_periods_service import load_from_db_sync, sync_from_db
from services.schedule_watch_service import configure_schedule_watch
from ui_utils import configure_ui_utils

logging.basicConfig(level=logging.INFO)

ADMIN_ALERT_INTERVAL_SECONDS = 900

MONTHS = [
    "",
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

MONTHS_NOM = [
    "",
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]

RU_HOLIDAYS = {
    (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 7), (1, 8),
    (2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4),
}

configure_keyboard_context(MONTHS, MONTHS_NOM, RU_HOLIDAYS)
configure_schedule_utils(MONTHS, RU_HOLIDAYS)
configure_ui_utils(MONTHS, MONTHS_NOM)

from services.sheet_loader import load_sheet  # noqa: E402

schedule.configure_schedule_service(load_sheet, MONTHS, RU_HOLIDAYS)
configure_departments_manager(schedule.clean_person_name, load_sheet)
configure_schedule_watch(MONTHS)
configure_admin_router(load_full_sheet)

dp = Dispatcher(storage=MemoryStorage())
dp.include_router(admin_router)


@dp.errors()
async def global_error_handler(event) -> bool:
    exception = event.exception
    logging.error("Admin bot error: %s\n%s", exception, traceback.format_exc())
    try:
        update = event.update
        msg = update.message or (
            update.callback_query.message if update.callback_query else None
        )
        if msg:
            await msg.answer(f"⚠️ Ошибка: {exception}")
    except Exception:
        pass
    return True


async def periods_sync_loop() -> None:
    last_refresh = now_local()
    while True:
        try:
            await asyncio.sleep(10)
            now = now_local()
            if (now - last_refresh).total_seconds() < SHEET_PERIODS_REFRESH_SECONDS:
                continue
            await sync_from_db()
            last_refresh = now
        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.warning("admin periods_sync_loop: %s", e)
            try:
                await run_health_alerts()
            except Exception:
                logging.exception("health alert after periods_sync failure")


async def maybe_refresh_sheet_cache() -> None:
    age = oldest_cache_age_seconds()
    if age is None or age < CACHE_REFRESH_SECONDS:
        return
    try:
        loaded, failed, errors = await load_all_sheet_gids()
        logging.info(
            "admin sheet cache refresh: age=%ss loaded=%s failed=%s",
            age,
            loaded,
            failed,
        )
        if failed and errors:
            logging.warning("admin sheet cache refresh errors: %s", "; ".join(errors[:3]))
    except Exception:
        logging.exception("admin sheet cache refresh failed")


async def sheet_cache_refresh_loop() -> None:
    await asyncio.sleep(120)
    while True:
        try:
            await maybe_refresh_sheet_cache()
        except asyncio.CancelledError:
            break
        except Exception:
            logging.exception("sheet_cache_refresh_loop")
        try:
            await asyncio.sleep(CACHE_REFRESH_SECONDS)
        except asyncio.CancelledError:
            break


async def health_alert_loop() -> None:
    await asyncio.sleep(60)
    while True:
        try:
            await maybe_refresh_sheet_cache()
            await run_health_alerts()
        except asyncio.CancelledError:
            break
        except Exception:
            logging.exception("health_alert_loop: ошибка проверки")
        try:
            await asyncio.sleep(ADMIN_ALERT_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            break


async def main():
    validate_admin_env()

    import os
    token = os.getenv("ADMIN_BOT_TOKEN")

    init_pg_pool()
    await asyncio.to_thread(load_from_db_sync)
    await load_full_sheet()

    bot = Bot(token=token)

    sync_task = asyncio.create_task(periods_sync_loop())
    sync_task.add_done_callback(
        lambda t: logging.exception(
            "periods_sync_loop crashed",
            exc_info=t.exception(),
        ) if not t.cancelled() and t.exception() else None
    )
    alert_task = asyncio.create_task(health_alert_loop())
    alert_task.add_done_callback(
        lambda t: logging.exception(
            "health_alert_loop crashed",
            exc_info=t.exception(),
        ) if not t.cancelled() and t.exception() else None
    )
    cache_task = asyncio.create_task(sheet_cache_refresh_loop())
    cache_task.add_done_callback(
        lambda t: logging.exception(
            "sheet_cache_refresh_loop crashed",
            exc_info=t.exception(),
        ) if not t.cancelled() and t.exception() else None
    )

    logging.info("Admin bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
