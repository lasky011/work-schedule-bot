"""Точка входа Telegram-бота расписания."""

import asyncio
import logging
import traceback
from datetime import timedelta

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app_config import (
    BOT_TOKEN,
    MINIAPP_ENABLED,
    MINIAPP_PORT,
    SHEET_PERIODS_REFRESH_SECONDS,
    now_local,
    validate_required_env,
)
from constants import SHIFT_END_NOTIFY
from departments_manager import refresh_departments
from departments_manager import configure_departments_manager
from db import USE_POSTGRES, get_db_connection, init_pg_pool
from keyboards import configure_keyboard_context
from keyboards.inline_miniapp import daily_notify_kb, hours_notify_kb
from repositories.shifts_repo import get_shift_for_date
from repositories.users_repo import get_notify_users
from routers.colleagues import router as colleagues_router
from routers.common import router as common_router
from routers.fallback import router as fallback_router
from routers.salary import router as salary_router
from routers.schedule import router as schedule_router
from routers.settings import router as settings_router
from schedule_utils import (
    configure_schedule_utils,
    detect_shift_type,
    get_day_type,
    get_standard_hours,
    is_work_shift,
)
from services import schedule_service as schedule
from services.compare_service import configure_compare_service
from services.salary_service import configure_salary_service
from services.sheet_loader import load_full_sheet, load_sheet
from services.sheet_periods_service import load_from_db_sync, sync_from_db
from services.schedule_watch_service import check_all_registered_users, configure_schedule_watch
from ui_utils import configure_ui_utils

validate_required_env()

logging.basicConfig(level=logging.INFO)

dp = Dispatcher(storage=MemoryStorage())

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


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id     BIGINT PRIMARY KEY,
        name        TEXT,
        notify      INTEGER DEFAULT 0,
        notify_time TEXT,
        role        TEXT,
        track_hours INTEGER DEFAULT 0,
        notify_hours INTEGER DEFAULT 0,
        notify_hours_time TEXT,
        theme       TEXT
    )
    """)

    extra_user_cols = [
        ("role", "TEXT"),
        ("track_hours", "INTEGER DEFAULT 0"),
        ("notify_hours", "INTEGER DEFAULT 0"),
        ("notify_hours_time", "TEXT"),
        ("theme", "TEXT"),
    ]
    for col, col_type in extra_user_cols:
        try:
            if USE_POSTGRES:
                cursor.execute(
                    f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {col_type}"
                )
            else:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
        except Exception:
            pass

    if USE_POSTGRES:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS shifts (
            id          SERIAL PRIMARY KEY,
            user_id     BIGINT NOT NULL,
            date        DATE NOT NULL,
            hours       NUMERIC(5,2) NOT NULL,
            shift_type  TEXT,
            is_standard BOOLEAN DEFAULT TRUE,
            note        TEXT,
            created_at  TIMESTAMP DEFAULT NOW(),
            UNIQUE (user_id, date)
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS shifts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            date        TEXT NOT NULL,
            hours       REAL NOT NULL,
            shift_type  TEXT,
            is_standard INTEGER DEFAULT 1,
            note        TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
            UNIQUE (user_id, date)
        )
        """)

    if USE_POSTGRES:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS schedule_snapshots (
            user_id     BIGINT PRIMARY KEY,
            snapshot    TEXT NOT NULL,
            updated_at  TIMESTAMP DEFAULT NOW()
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS schedule_snapshots (
            user_id     INTEGER PRIMARY KEY,
            snapshot    TEXT NOT NULL,
            updated_at  TEXT DEFAULT (datetime('now'))
        )
        """)

    conn.commit()
    cursor.close()
    conn.close()


schedule.configure_schedule_service(load_sheet, MONTHS, RU_HOLIDAYS)
configure_departments_manager(schedule.clean_person_name, load_sheet)
configure_salary_service(find_row=schedule.find_row, get_day_value=schedule.get_day_value)
configure_compare_service(find_row=schedule.find_row, get_day_value=schedule.get_day_value)
configure_schedule_watch(MONTHS)

SCHEDULE_WATCH_SECONDS = 180


async def hours_notification_loop(bot) -> None:
    sent = {}
    last_cleanup = now_local().date()

    while True:
        try:
            now = now_local()
            current_time = now.strftime("%H:%M")

            today_date = now.date()
            if today_date != last_cleanup:
                cutoff = (today_date - timedelta(days=2)).strftime("%Y-%m-%d")
                sent = {k: v for k, v in sent.items()
                        if k.split("-hours-")[-1] >= cutoff}
                last_cleanup = today_date

            if now.hour < 12:
                shift_dt = now - timedelta(days=1)
            else:
                shift_dt = now

            shift_day = shift_dt.day
            shift_month = shift_dt.month
            shift_year = shift_dt.year
            shift_key = shift_dt.strftime("%Y-%m-%d")
            day_type = get_day_type(shift_dt)

            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT user_id, name, role FROM users "
                    "WHERE notify_hours=1 AND name IS NOT NULL"
                )
                users = cursor.fetchall()
                cursor.close()
                conn.close()
            except Exception as e:
                logging.error("hours_notification_loop DB error: %s", e)
                await asyncio.sleep(60)
                continue

            for _hr in users:
                user_id, name = _hr[0], _hr[1]
                hr_role = _hr[2] if len(_hr) > 2 else None
                key = f"{user_id}-hours-{shift_key}"
                if sent.get(key):
                    continue

                try:
                    if not schedule.is_day_published(shift_day, shift_month, shift_year):
                        continue

                    row, _ = await schedule.find_row(
                        name, shift_day, shift_month, shift_year, target_role=hr_role,
                    )
                    if not row:
                        continue

                    value = await schedule.get_day_value(row, shift_day, shift_month, shift_year)
                    if not is_work_shift(value):
                        continue

                    shift_type = detect_shift_type(value)
                    if not shift_type:
                        continue

                    notify_time = SHIFT_END_NOTIFY.get((shift_type, day_type))
                    if not notify_time or notify_time != current_time:
                        continue

                    existing = await get_shift_for_date(user_id, shift_key)
                    if existing:
                        sent[key] = True
                        continue

                    shift_label = {"morning": "утро", "evening": "вечер"}.get(shift_type, "")
                    std_hours = get_standard_hours(shift_type, shift_dt)
                    lines = ["⏱ Не забудь внести часы за смену!"]

                    if shift_label:
                        line = f"По графику {shift_day} {MONTHS[shift_month]}: {shift_label}"
                        if std_hours:
                            line += f", стандартная смена — {std_hours} ч"
                        lines.append(line)

                    await bot.send_message(
                        user_id, "\n".join(lines), reply_markup=hours_notify_kb(shift_key),
                    )
                    sent[key] = True

                except Exception as e:
                    logging.exception(
                        "hours_notification_loop error for user_id=%s name=%s: %s",
                        user_id, name, e,
                    )

        except Exception as e:
            logging.exception("hours_notification_loop: критическая ошибка цикла: %s", e)

        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            break


async def notification_loop(bot):
    sent = {}
    last_cleanup = now_local().date()
    last_dept_refresh = now_local()
    last_periods_refresh = now_local()

    while True:
        now = now_local()
        current_time = now.strftime("%H:%M")

        if (now - last_dept_refresh).total_seconds() > 3600:
            try:
                await refresh_departments(force=True)
                last_dept_refresh = now
                logging.info("refresh_departments: обновлено")
            except Exception as e:
                logging.warning("refresh_departments error: %s", e)

        if (now - last_periods_refresh).total_seconds() > SHEET_PERIODS_REFRESH_SECONDS:
            try:
                await sync_from_db()
                last_periods_refresh = now
            except Exception as e:
                logging.warning("sheet_periods sync error: %s", e)

        today_key = now.strftime("%Y-%m-%d")
        today_date = now.date()
        if today_date != last_cleanup:
            cutoff = (today_date - timedelta(days=2)).strftime("%Y-%m-%d")
            sent = {k: v for k, v in sent.items() if k.split("-", 1)[1][:10] >= cutoff}
            last_cleanup = today_date

        for _nr in await get_notify_users():
            user_id, name, notify_time = _nr[0], _nr[1], _nr[2]
            nr_role = _nr[3] if len(_nr) > 3 else None
            if notify_time != current_time:
                continue

            key = f"{user_id}-{today_key}-{notify_time}"
            if sent.get(key):
                continue

            try:
                text = await schedule.get_notification_text(name, target_role=nr_role)
                if text:
                    await bot.send_message(user_id, text, reply_markup=daily_notify_kb())
                    sent[key] = True
                else:
                    logging.warning(
                        "notification_loop: пустой текст user_id=%s name=%s notify_time=%s role=%s",
                        user_id, name, notify_time, nr_role,
                    )
            except Exception as e:
                logging.exception(
                    "notification_loop: ошибка user_id=%s name=%s notify_time=%s role=%s: %s",
                    user_id, name, notify_time, nr_role, e,
                )

        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            break


async def schedule_watch_loop() -> None:
    await asyncio.sleep(30)
    while True:
        try:
            await check_all_registered_users()
        except Exception:
            logging.exception("schedule_watch_loop: критическая ошибка цикла")
        try:
            await asyncio.sleep(SCHEDULE_WATCH_SECONDS)
        except asyncio.CancelledError:
            break


dp.include_router(common_router)
dp.include_router(settings_router)
dp.include_router(schedule_router)
dp.include_router(salary_router)
dp.include_router(colleagues_router)
dp.include_router(fallback_router)


@dp.errors()
async def global_error_handler(event) -> bool:
    exception = event.exception
    logging.error("Необработанная ошибка: %s\n%s", exception, traceback.format_exc())
    try:
        update = event.update
        msg = None
        if update.message:
            msg = update.message
        elif update.callback_query:
            msg = update.callback_query.message
        if msg:
            await msg.answer(
                "⚠️ Что-то пошло не так. Попробуй ещё раз или вернись в главное меню."
            )
    except Exception:
        pass
    return True


async def start_miniapp_server() -> None:
    import uvicorn
    from api.app import create_app

    config = uvicorn.Config(
        create_app(),
        host="0.0.0.0",
        port=MINIAPP_PORT,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    await asyncio.to_thread(init_db)
    init_pg_pool()
    await asyncio.to_thread(load_from_db_sync)

    if not BOT_TOKEN:
        print("Ошибка: BOT_TOKEN не найден в .env")
        return

    bot = Bot(token=BOT_TOKEN)

    miniapp_task = None
    if MINIAPP_ENABLED:
        miniapp_task = asyncio.create_task(start_miniapp_server())
        miniapp_task.add_done_callback(
            lambda t: logging.exception(
                "miniapp_server: фоновая задача завершилась с ошибкой",
                exc_info=t.exception(),
            ) if not t.cancelled() and t.exception() else None
        )
        logging.info("Mini App HTTP на порту %s", MINIAPP_PORT)

    await load_full_sheet()

    notification_task = asyncio.create_task(notification_loop(bot))
    notification_task.add_done_callback(
        lambda t: logging.exception(
            "notification_loop: фоновая задача завершилась с ошибкой",
            exc_info=t.exception(),
        ) if not t.cancelled() and t.exception() else None
    )
    hours_task = asyncio.create_task(hours_notification_loop(bot))
    hours_task.add_done_callback(
        lambda t: logging.exception(
            "hours_notification_loop: фоновая задача завершилась с ошибкой",
            exc_info=t.exception(),
        ) if not t.cancelled() and t.exception() else None
    )
    schedule_watch_task = asyncio.create_task(schedule_watch_loop())
    schedule_watch_task.add_done_callback(
        lambda t: logging.exception(
            "schedule_watch_loop: фоновая задача завершилась с ошибкой",
            exc_info=t.exception(),
        ) if not t.cancelled() and t.exception() else None
    )

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
