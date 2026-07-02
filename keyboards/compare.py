import calendar

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from app_config import now_local
from services.sheet_periods_service import SHEET_GID_MAP
from ui_utils import month_label


def get_available_periods():
    """
    Актуальные периоды из SHEET_GID_MAP.

    Формат элемента: (year, month, start_day, end_day)
    """
    result = []

    for key in sorted(SHEET_GID_MAP.keys()):
        if not isinstance(key, tuple) or len(key) != 3:
            continue

        year, month, start_day = key
        if start_day == 1:
            end_day = 15
        else:
            end_day = calendar.monthrange(year, month)[1]

        try:
            now_local().replace(
                year=year,
                month=month,
                day=end_day,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            ).date()
        except Exception:
            continue

        result.append((year, month, start_day, end_day))

    return result


def compare_period_kb():
    """Клавиатура выбора периода для сравнения."""
    buttons = []

    for year, month, start_day, end_day in get_available_periods():
        month_name = month_label(month)
        buttons.append([KeyboardButton(text=f"📅 {start_day}–{end_day} {month_name} {year}")])

    buttons.append([KeyboardButton(text="⬅️ Назад к сравнению")])
    buttons.append([KeyboardButton(text="🏠 Главное меню")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def compare_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить сотрудника")],
            [KeyboardButton(text="✅ Посчитать совпадения")],
            [KeyboardButton(text="🗑 Очистить список")],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True,
    )


def week_kb(week_days):
    """Кнопки с днями недели + навигация ◀️ ▶️"""
    weekdays_short = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    buttons = []
    row = []

    for dt in week_days:
        label = f"{weekdays_short[dt.weekday()]} {dt.day}"
        row.append(KeyboardButton(text=f"📅 {label}"))
        if len(row) == 3:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append([
        KeyboardButton(text="◀️ Пред. неделя"),
        KeyboardButton(text="▶️ След. неделя"),
    ])
    buttons.append([KeyboardButton(text="🏠 Главное меню")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
