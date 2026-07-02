import calendar

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from app_config import now_local
from services.sheet_periods_service import SHEET_GID_MAP
from keyboards import context
from ui_utils import fmt_hours, month_label


def salary_kb(track_hours: int = 0) -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton(text="📊 Примерная зарплата")]]
    if track_hours:
        keyboard += [
            [KeyboardButton(text="⏱ Внести смену"), KeyboardButton(text="📋 История смен")],
        ]
    keyboard += [
        [KeyboardButton(text="⚙️ Настройки учёта")],
        [KeyboardButton(text="🏠 Главное меню")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def salary_period_kb() -> ReplyKeyboardMarkup:
    now = now_local()
    month, year = now.month, now.year
    month_name = context.MONTHS_NOM[month]

    if month == 1:
        prev_month, prev_year = 12, year - 1
    else:
        prev_month, prev_year = month - 1, year
    prev_month_name = context.MONTHS_NOM[prev_month]
    prev_end = calendar.monthrange(prev_year, prev_month)[1]
    cur_end = calendar.monthrange(year, month)[1]

    keyboard = [
        [KeyboardButton(text="📅 Текущий период")],
        [
            KeyboardButton(text="1-15 " + month_name),
            KeyboardButton(text="16-" + str(cur_end) + " " + month_name),
        ],
        [
            KeyboardButton(text="1-15 " + prev_month_name),
            KeyboardButton(text="16-" + str(prev_end) + " " + prev_month_name),
        ],
        [KeyboardButton(text="⬅️ Назад к зарплате")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def salary_settings_kb(track_hours: int = 0, notify_hours: int = 0) -> ReplyKeyboardMarkup:
    track_label = "🔴 Выключить учёт часов" if track_hours else "⬜ Включить учёт часов"
    notify_label = "🔔 Уведомление включено" if notify_hours else "🔕 Уведомление выключено"
    keyboard = [[KeyboardButton(text=track_label)]]
    if track_hours:
        keyboard += [
            [KeyboardButton(text=notify_label)],
            [KeyboardButton(text="🗑 Удалить смену из истории")],
        ]
    keyboard.append([KeyboardButton(text="⬅️ Назад к зарплате")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def salary_settings_delete_kb(shifts) -> ReplyKeyboardMarkup:
    keyboard = []
    for row in shifts:
        date, hours, shift_type, is_standard, note = row
        shift_label = {"morning": "утро", "evening": "вечер"}.get(shift_type or "", "")
        keyboard.append([KeyboardButton(text="🗑 " + str(date) + " — " + str(hours) + " ч " + shift_label)])
    keyboard.append([KeyboardButton(text="⬅️ Назад к настройкам")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def shift_date_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📥 Сегодня"), KeyboardButton(text="📥 Вчера")],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True,
    )


def shift_hours_kb(standard_hours) -> ReplyKeyboardMarkup:
    keyboard = []
    if standard_hours:
        keyboard.append([KeyboardButton(text="✅ Стандартная (" + str(standard_hours) + " ч)")])
    keyboard += [
        [KeyboardButton(text="✍️ Указать своё время")],
        [KeyboardButton(text="🏠 Главное меню")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_shift_history_months():
    """Месяцы для истории смен на основе SHEET_GID_MAP."""
    months = set()

    for key in SHEET_GID_MAP.keys():
        if not isinstance(key, tuple) or len(key) != 3:
            continue

        year, month, _start_day = key
        months.add((year, month))

    return sorted(months)


def shift_history_month_kb():
    buttons = []

    for year, month in get_shift_history_months():
        buttons.append([KeyboardButton(text=f"🧾 Месяц: {month_label(month)} {year}")])

    buttons.append([KeyboardButton(text="⬅️ Назад к зарплате")])
    buttons.append([KeyboardButton(text="🏠 Главное меню")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def shift_history_period_kb(month=None, year=None):
    now = now_local()
    month = month or now.month
    year = year or now.year

    last_day = calendar.monthrange(year, month)[1]
    month_name = month_label(month)

    keyboard = [
        [KeyboardButton(text=f"🧾 Период: 1–15 {month_name} {year}")],
        [KeyboardButton(text=f"🧾 Период: 16–{last_day} {month_name} {year}")],
        [KeyboardButton(text="⬅️ Назад к выбору месяца")],
        [KeyboardButton(text="⬅️ Назад к зарплате")],
        [KeyboardButton(text="🏠 Главное меню")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def shift_history_actions_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🗑 Удалить смену из этого периода")],
            [KeyboardButton(text="⬅️ Назад к выбору периода")],
            [KeyboardButton(text="💰 Зарплата")],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True,
    )


def shift_history_delete_kb(shifts):
    keyboard = []

    for date_str, hours, shift_type, is_standard, note in shifts:
        shift_label = ""
        if shift_type == "morning":
            shift_label = "утро"
        elif shift_type == "evening":
            shift_label = "вечер"
        elif shift_type:
            shift_label = str(shift_type)

        label = f"❌ {date_str} — {fmt_hours(hours)} ч"
        if shift_label:
            label += f" {shift_label}"

        keyboard.append([KeyboardButton(text=label)])

    keyboard.append([KeyboardButton(text="⬅️ Назад к истории")])
    keyboard.append([KeyboardButton(text="💰 Зарплата")])
    keyboard.append([KeyboardButton(text="🏠 Главное меню")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
