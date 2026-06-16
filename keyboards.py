from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from constants import SHEET_GID_MAP
from app_config import now_local
import calendar


# Эти значения будут переданы из bot.py после импорта функций.
MONTHS = None
MONTHS_NOM = None
RU_HOLIDAYS = None


def configure_keyboard_context(months, months_nom, ru_holidays):
    global MONTHS, MONTHS_NOM, RU_HOLIDAYS
    MONTHS = months
    MONTHS_NOM = months_nom
    RU_HOLIDAYS = ru_holidays



def get_available_periods():
    """
    Актуальные периоды из SHEET_GID_MAP.

    Период появляется, если для него есть gid.
    Период исчезает, если дата конца периода уже прошла.
    Формат элемента: (year, month, start_day, end_day)
    """
    today = now_local().date()
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
            period_end_date = now_local().replace(
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

        # Показываем все периоды, чтобы можно было смотреть старые совпадения
        result.append((year, month, start_day, end_day))

    return result


def _month_label_for_period(month):
    """Название месяца для кнопки периода."""
    try:
        return MONTHS_NOM[month]
    except Exception:
        try:
            return MONTHS[month]
        except Exception:
            return str(month)


def compare_period_kb():
    """Клавиатура выбора периода для сравнения."""
    buttons = []

    for year, month, start_day, end_day in get_available_periods():
        month_name = _month_label_for_period(month)
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
        resize_keyboard=True
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


