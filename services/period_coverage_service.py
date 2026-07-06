"""Проверка, что для графика есть gid в sheet_periods."""

import calendar
from datetime import date, timedelta

from app_config import now_local
from services.sheet_periods_service import SHEET_GID_MAP

WARN_DAYS_BEFORE_NEXT_PERIOD = 2


def period_key_for_date(day: int, month: int, year: int) -> tuple[int, int, int]:
    return (year, month, 1 if day <= 15 else 16)


def _next_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


def current_period_key(on: date | None = None) -> tuple[int, int, int]:
    today = on or now_local().date()
    return period_key_for_date(today.day, today.month, today.year)


def next_period_key_and_start(on: date | None = None) -> tuple[tuple[int, int, int], date]:
    today = on or now_local().date()
    if today.day <= 15:
        return (today.year, today.month, 16), date(today.year, today.month, 16)

    year, month = _next_month(today.year, today.month)
    return (year, month, 1), date(year, month, 1)


def missing_period_keys(days_ahead: int = 14) -> list[tuple[int, int, int]]:
    """Все пропущенные периоды в окне — для диагностики, не для алертов."""
    today = now_local().date()
    needed: set[tuple[int, int, int]] = set()
    for offset in range(days_ahead + 1):
        dt = today + timedelta(days=offset)
        needed.add(period_key_for_date(dt.day, dt.month, dt.year))
    return sorted(key for key in needed if key not in SHEET_GID_MAP)


def missing_period_alerts(
    *,
    warn_days_before: int = WARN_DAYS_BEFORE_NEXT_PERIOD,
    on: date | None = None,
) -> list[tuple[int, int, int]]:
    """Периоды, по которым нужно предупредить админа.

    - Текущий период без gid — сразу (график уже должен работать).
    - Следующий период без gid — только за warn_days_before дней до его начала.
    """
    today = on or now_local().date()
    alerts: list[tuple[int, int, int]] = []

    current = current_period_key(today)
    if current not in SHEET_GID_MAP:
        alerts.append(current)
        return alerts

    next_key, next_start = next_period_key_and_start(today)
    if next_key in SHEET_GID_MAP:
        return alerts

    days_until = (next_start - today).days
    if days_until <= warn_days_before:
        alerts.append(next_key)

    return alerts


def format_period_key(key: tuple[int, int, int]) -> str:
    year, month, start_day = key
    end_day = 15 if start_day == 1 else calendar.monthrange(year, month)[1]
    months = [
        "",
        "янв", "фев", "мар", "апр", "май", "июн",
        "июл", "авг", "сен", "окт", "ноя", "дек",
    ]
    return f"{start_day}–{end_day} {months[month]} {year}"
