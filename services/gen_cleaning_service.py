"""Генеральная уборка: формула по умолчанию и ручные дни месяца из админки."""

from __future__ import annotations

import calendar
import logging
from datetime import date, datetime, timedelta

FIRST_GEN_CLEANING = date(2026, 7, 8)
GEN_CLEANING_NOTIFY_TIME = "22:00"
GEN_CLEANING_HOUR = 9
CADENCE_DAYS = 14

# (year, month) → дни. Ключ есть = месяц задан вручную, даже если список пустой.
_overrides: dict[tuple[int, int], frozenset[int]] = {}


def reset_overrides() -> None:
    _overrides.clear()


def apply_overrides(rows: list[tuple[int, int, list[int]]]) -> None:
    _overrides.clear()
    for year, month, days in rows:
        _overrides[(int(year), int(month))] = frozenset(
            int(day) for day in days if 1 <= int(day) <= 31
        )


def month_has_override(year: int, month: int) -> bool:
    return (year, month) in _overrides


def is_cadence_cleaning_day(d: date) -> bool:
    if d.weekday() != 2:
        return False
    delta = (d - FIRST_GEN_CLEANING).days
    if delta < 0:
        return False
    return delta % CADENCE_DAYS == 0


def cadence_days_in_month(year: int, month: int) -> list[int]:
    last = calendar.monthrange(year, month)[1]
    return [
        day for day in range(1, last + 1)
        if is_cadence_cleaning_day(date(year, month, day))
    ]


def effective_days_in_month(year: int, month: int) -> list[int]:
    key = (year, month)
    if key in _overrides:
        return sorted(_overrides[key])
    return cadence_days_in_month(year, month)


def is_gen_cleaning_day(d: date) -> bool:
    key = (d.year, d.month)
    if key in _overrides:
        return d.day in _overrides[key]
    return is_cadence_cleaning_day(d)


def is_gen_cleaning_notify_evening(d: date) -> bool:
    """Вечер накануне дня ген уборки (в 22:00)."""
    return is_gen_cleaning_day(d + timedelta(days=1))


def cleaning_date_due_for_notice(now: datetime) -> date | None:
    """Если сейчас окно напоминания — дата уборки, иначе None."""
    if now.strftime("%H:%M") < GEN_CLEANING_NOTIFY_TIME:
        return None
    tomorrow = now.date() + timedelta(days=1)
    if is_gen_cleaning_day(tomorrow):
        return tomorrow
    return None


def gen_cleaning_notification_text() -> str:
    return (
        "🧹 Завтра ген уборка в 9:00\n"
        "Не забудь поставить будильник!"
    )


def load_from_db_sync() -> int:
    from repositories.gen_cleaning_repo import ensure_schema_sync, _fetch_overrides_sync

    try:
        ensure_schema_sync()
        rows = _fetch_overrides_sync()
    except Exception as e:
        logging.warning("gen_cleaning: не удалось загрузить дни из БД: %s", e)
        return len(_overrides)
    apply_overrides(rows)
    return len(_overrides)


async def reload_from_db(quiet: bool = False) -> int:
    import asyncio

    count = await asyncio.to_thread(load_from_db_sync)
    if not quiet:
        logging.info("gen_cleaning: загружено ручных месяцев: %s", count)
    return count
