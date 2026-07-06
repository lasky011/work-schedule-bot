"""Генеральная уборка: расписание и тексты уведомлений."""

from datetime import date, timedelta

FIRST_GEN_CLEANING = date(2026, 7, 8)
GEN_CLEANING_NOTIFY_TIME = "22:00"
GEN_CLEANING_HOUR = 9
CADENCE_DAYS = 14


def is_gen_cleaning_day(d: date) -> bool:
    if d.weekday() != 2:
        return False
    delta = (d - FIRST_GEN_CLEANING).days
    if delta < 0:
        return False
    return delta % CADENCE_DAYS == 0


def is_gen_cleaning_notify_evening(d: date) -> bool:
    """Вечер накануне ген уборки (вторник 22:00 перед средой)."""
    return is_gen_cleaning_day(d + timedelta(days=1))


def gen_cleaning_notification_text() -> str:
    return (
        "🧹 Завтра ген уборка в 9:00\n"
        "Не забудь поставить будильник!"
    )
