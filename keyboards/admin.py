"""Клавиатуры admin-бота."""

import calendar

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app_config import now_local
from ui_utils import month_label

BTN_PERIODS = "📅 Периоды"
BTN_ADD_PERIOD = "➕ Добавить период"
BTN_RELOAD_SHEETS = "🔄 Листы"
BTN_RELOAD_PERIODS = "🔄 Периоды"
BTN_STATUS = "🛠 Статус"
BTN_CACHE = "🧠 Кэш"
BTN_HELP = "📋 Справка"
BTN_CANCEL = "❌ Отмена"

CB_EDIT_PERIOD = "edit_period"
CB_RELOAD_MENU = "reload_menu"
CB_RELOAD_SHEETS = "reload_sheets"
CB_RELOAD_PERIODS = "reload_periods"


def admin_main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_PERIODS), KeyboardButton(text=BTN_ADD_PERIOD)],
            [KeyboardButton(text=BTN_RELOAD_SHEETS), KeyboardButton(text=BTN_RELOAD_PERIODS)],
            [KeyboardButton(text=BTN_STATUS), KeyboardButton(text=BTN_CACHE)],
            [KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
    )


def admin_cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
        resize_keyboard=True,
    )


def upcoming_month_choices(months_ahead: int = 4) -> list[tuple[int, int]]:
    now = now_local()
    year, month = now.year, now.month
    result: list[tuple[int, int]] = []
    for offset in range(months_ahead):
        total = (month - 1) + offset
        result.append((year + total // 12, (total % 12) + 1))
    return result


def add_period_month_kb() -> ReplyKeyboardMarkup:
    rows = []
    row: list[KeyboardButton] = []
    for year, month in upcoming_month_choices():
        row.append(KeyboardButton(text=f"{month_label(month)} {year}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([KeyboardButton(text=BTN_CANCEL)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def add_period_half_kb(year: int, month: int) -> ReplyKeyboardMarkup:
    last_day = calendar.monthrange(year, month)[1]
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=f"1–15 {month_label(month)}")],
            [KeyboardButton(text=f"16–{last_day} {month_label(month)}")],
            [KeyboardButton(text=BTN_CANCEL)],
        ],
        resize_keyboard=True,
    )


def periods_inline_kb(period_keys: list[tuple[int, int, int]]) -> InlineKeyboardMarkup:
    rows = []
    for year, month, start_day in period_keys:
        if start_day == 1:
            end_day = 15
        else:
            end_day = calendar.monthrange(year, month)[1]
        label = f"✏️ {start_day}–{end_day} {month_label(month)} {year}"
        rows.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"{CB_EDIT_PERIOD}:{year}:{month}:{start_day}",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reload_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Листы", callback_data=CB_RELOAD_SHEETS),
                InlineKeyboardButton(text="🔄 Периоды из БД", callback_data=CB_RELOAD_PERIODS),
            ],
        ]
    )
