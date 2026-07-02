"""Календарь для внесения смен — русская локализация."""

from aiogram_calendar import SimpleCalendar

RU_DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
RU_MONTHS = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def shift_calendar() -> SimpleCalendar:
    cal = SimpleCalendar(cancel_btn="Отмена", today_btn="Сегодня")
    try:
        cal = SimpleCalendar(locale="ru_RU", cancel_btn="Отмена", today_btn="Сегодня")
    except Exception:
        pass
    cal._labels.days_of_week = list(RU_DAYS)
    cal._labels.months = list(RU_MONTHS)
    return cal
