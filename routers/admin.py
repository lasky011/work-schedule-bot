"""Админ-команды бота."""

import calendar
import logging
from typing import Awaitable, Callable

from aiogram import F, Router
from aiogram.types import Message

from app_config import APP_TIMEZONE_NAME, is_admin, now_local
from constants import SHEET_GID_MAP
from db import get_db_connection
from keyboards import get_available_periods
from sheets_client import cached_df, cached_time, clear_sheet_cache
from ui_utils import month_label

router = Router(name="admin")

_load_full_sheet: Callable[[], Awaitable] | None = None


def configure_admin_router(load_full_sheet):
    global _load_full_sheet
    _load_full_sheet = load_full_sheet


@router.message(F.text == "/health")
async def admin_health(message: Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    now = now_local()
    db_status = "unknown"
    notify_count = "?"
    notify_hours_count = "?"

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE notify=1")
        notify_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM users WHERE notify_hours=1")
        notify_hours_count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"

    text = (
        "🛠 Health check\n\n"
        f"Время бота: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Таймзона: {APP_TIMEZONE_NAME}\n"
        f"БД: {db_status}\n"
        f"Пользователей с уведомлениями смен: {notify_count}\n"
        f"Пользователей с уведомлениями часов: {notify_hours_count}\n"
        f"Периодов в SHEET_GID_MAP: {len(SHEET_GID_MAP)}\n"
        f"Кэшированных gid: {len(cached_df)}\n"
    )
    await message.answer(text)


@router.message(F.text == "/periods")
async def admin_periods(message: Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    actual = set(get_available_periods())
    lines = ["📅 Периоды графика\n"]
    for year, month, start_day in sorted(SHEET_GID_MAP.keys()):
        if start_day == 1:
            end_day = 15
        else:
            end_day = calendar.monthrange(year, month)[1]
        status = "актуален" if (year, month, start_day, end_day) in actual else "прошёл"
        gid = SHEET_GID_MAP[(year, month, start_day)]
        lines.append(
            f"{start_day}–{end_day} {month_label(month)} {year}: gid={gid} ({status})"
        )

    await message.answer("\n".join(lines))


@router.message(F.text == "/cache")
async def admin_cache(message: Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    now = now_local()
    if not cached_df:
        return await message.answer("🧹 Кэш Google Sheets пуст.")

    lines = ["🧠 Кэш Google Sheets\n"]
    for gid, df in cached_df.items():
        ts = cached_time.get(gid)
        age = "?"
        if ts:
            try:
                age = f"{int((now - ts).total_seconds())} сек."
            except Exception:
                age = "?"
        shape = getattr(df, "shape", None)
        lines.append(f"gid={gid}: age={age}, shape={shape}")

    await message.answer("\n".join(lines))


@router.message(F.text == "/reload_sheets")
async def admin_reload_sheets(message: Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    if _load_full_sheet is None:
        return await message.answer("⚠️ admin router не настроен.")

    clear_sheet_cache()
    try:
        await _load_full_sheet()
        await message.answer("✅ Кэш Google Sheets сброшен и таблицы загружены заново.")
    except Exception as e:
        logging.exception("admin_reload_sheets error: %s", e)
        await message.answer(f"⚠️ Кэш сброшен, но загрузка таблиц завершилась ошибкой: {e}")
