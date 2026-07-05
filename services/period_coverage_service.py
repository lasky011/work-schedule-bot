"""Проверка, что для ближайших дат есть gid в sheet_periods."""

import calendar
from datetime import timedelta

from app_config import now_local
from services.sheet_periods_service import SHEET_GID_MAP


def period_key_for_date(day: int, month: int, year: int) -> tuple[int, int, int]:
    return (year, month, 1 if day <= 15 else 16)


def missing_period_keys(days_ahead: int = 14) -> list[tuple[int, int, int]]:
    today = now_local().date()
    needed: set[tuple[int, int, int]] = set()
    for offset in range(days_ahead + 1):
        dt = today + timedelta(days=offset)
        needed.add(period_key_for_date(dt.day, dt.month, dt.year))
    return sorted(key for key in needed if key not in SHEET_GID_MAP)


def format_period_key(key: tuple[int, int, int]) -> str:
    year, month, start_day = key
    end_day = 15 if start_day == 1 else calendar.monthrange(year, month)[1]
    months = [
        "",
        "янв", "фев", "мар", "апр", "май", "июн",
        "июл", "авг", "сен", "окт", "ноя", "дек",
    ]
    return f"{start_day}–{end_day} {months[month]} {year}"
