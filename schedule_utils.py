import re
import calendar

from app_config import now_local
from constants import SHIFT_HOURS


# Эти значения задаются из bot.py после импорта.
MONTHS = None
RU_HOLIDAYS = None


def configure_schedule_utils(months, ru_holidays):
    global MONTHS, RU_HOLIDAYS
    MONTHS = months
    RU_HOLIDAYS = ru_holidays


def clean_value(value):
    text = str(value).strip()

    if not text:
        return ""

    if text.lower() in ["nan", "none", "выходной", "-", "—"]:
        return ""

    return text

# Текстовые значения, которые считаются рабочей сменой (без цифр)
_WORK_SHIFT_WORDS = {"оф"}


def detect_shift_type(value: str) -> str | None:
    """Определяет тип смены (morning/evening) по значению из таблицы.

    Форматы: 11:00, 16:00, 9:00, 16-23, 16-01,
    17:30-01, 19-04, 11-19, Оф.
    """
    if not value:
        return None
    text = str(value).strip()
    # «До 04:00» и прочие заметки — не смена
    if text.lower().startswith("до"):
        return None
    # Извлекаем первое число — час начала смены
    m = re.match(r"(\d{1,2})", text)
    if not m:
        return None
    hour = int(m.group(1))
    return "morning" if hour < 14 else "evening"


def is_work_shift(value):
    text = clean_value(value)

    if not text:
        return False

    # Текстовые смены (Оф — менеджер за официанта)
    if text.lower() in _WORK_SHIFT_WORDS:
        return True

    # Начинается с цифры часа — рабочая смена
    if re.match(r"^\d{1,2}[:\-\s]", text) or re.match(r"^\d{1,2}$", text):
        return True

    return False


def detect_shift(value):
    text = clean_value(value)

    if not text:
        return "выходной"

    # Извлекаем час начала для определения утро/вечер
    m = re.match(r"(\d{1,2})", text)
    if m:
        hour = int(m.group(1))
        label = "утро" if hour < 14 else "вечер"
        return f"{text} — {label}"

    return text


def get_day_type(date) -> str:
    # Пт (4) и Сб (5) — выходные дни ресторана
    # Пн–Чт (0–3) и Вс (6) — будние дни ресторана
    if date.weekday() in (4, 5):
        return "weekend"
    return "weekday"


def get_standard_hours(shift_type: str | None, date) -> float | None:
    if not shift_type:
        return None
    return SHIFT_HOURS.get((shift_type, get_day_type(date)))


def format_date(day, month=None, year=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year
    weekday_index = datetime(year, month, day).weekday()
    label = WEEKDAYS[weekday_index]
    is_red = weekday_index in (4, 5) or (month, day) in RU_HOLIDAYS
    label = f"❗ {label}" if is_red else label
    return f"{day} {MONTHS[month]} ({label})"


def current_period(month=None, year=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year
    max_day = calendar.monthrange(year, month)[1]
    today = now_local().day

    # если запрашиваем текущий месяц — период зависит от сегодняшнего дня
    if month == now.month and year == now.year:
        if today <= 15:
            return 1, 15
        return 16, max_day

    # если запрашиваем будущий месяц — показываем доступный период
    # проверяем какие GID есть для этого месяца
    has_first = (year, month, 1) in SHEET_GID_MAP
    has_second = (year, month, 16) in SHEET_GID_MAP

    if has_first and has_second:
        return 1, max_day
    if has_first:
        return 1, 15
    if has_second:
        return 16, max_day
    return 1, max_day


