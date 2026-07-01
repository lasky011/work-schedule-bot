"""Бизнес-логика зарплаты, учёта смен и истории."""

import calendar
import re
from datetime import datetime
from typing import Awaitable, Callable

from constants import RATES
from repositories.shifts_repo import get_shifts_for_month
from schedule_utils import detect_shift_type, get_standard_hours, is_work_shift
from ui_utils import fmt_hours, month_label
import ui_utils

_find_row: Callable[..., Awaitable] | None = None
_get_day_value: Callable[..., Awaitable] | None = None


def configure_salary_service(find_row, get_day_value):
    global _find_row, _get_day_value
    _find_row = find_row
    _get_day_value = get_day_value


def get_role_key(role: str | None) -> str | None:
    if not role:
        return None
    parts = role.split(" ", 1)
    return parts[1] if len(parts) == 2 else role


def _month_label_variants(month: int) -> set[str]:
    names = set()
    if ui_utils.MONTHS and month < len(ui_utils.MONTHS):
        names.add(str(ui_utils.MONTHS[month]))
    if ui_utils.MONTHS_NOM and month < len(ui_utils.MONTHS_NOM):
        names.add(str(ui_utils.MONTHS_NOM[month]))
    return names


def parse_shift_history_month_button(text: str) -> tuple[int, int] | None:
    m = re.match(r"^🧾 Месяц: (.+) (\d{4})$", text.strip())
    if not m:
        return None

    month_label_text = m.group(1).strip()
    year = int(m.group(2))

    for month in range(1, 13):
        if month_label_text in _month_label_variants(month):
            return year, month

    return None


def parse_shift_history_period_button(text: str) -> tuple[int, int, int, int] | None:
    m = re.match(r"^🧾 Период: (\d+)–(\d+) (.+) (\d{4})$", text.strip())
    if not m:
        return None

    start_day = int(m.group(1))
    end_day = int(m.group(2))
    month_label_text = m.group(3).strip()
    year = int(m.group(4))

    for month in range(1, 13):
        if month_label_text in _month_label_variants(month):
            return year, month, start_day, end_day

    return None


async def build_salary_stats_text(
    user_id: int,
    user: tuple,
    year: int,
    month: int,
    period_start: int,
    period_end: int,
) -> str:
    if _find_row is None or _get_day_value is None:
        raise RuntimeError("salary_service не настроен: вызови configure_salary_service()")

    name = user[1]
    role = user[4] if len(user) > 4 else None
    track_hours = user[5] if len(user) > 5 else 0

    period_name = str(period_start) + "-" + str(period_end)
    month_name = month_label(month) + " " + str(year) + " (" + period_name + ")"

    schedule_shifts = 0
    schedule_hours = 0.0
    no_data = True

    for day in range(period_start, period_end + 1):
        try:
            row, _ = await _find_row(name, day, month, year, target_role=role)
            if row:
                no_data = False
                value = await _get_day_value(row, day, month, year)
                if is_work_shift(value):
                    schedule_shifts += 1
                    shift_type = detect_shift_type(value)
                    dt = datetime(year, month, day)
                    hours = get_standard_hours(shift_type, dt) or 12.0
                    schedule_hours += hours
        except (ValueError, ConnectionError):
            pass

    rate = RATES.get(get_role_key(role) or "", 0)
    lines = ["📊 " + month_name, ""]

    if no_data:
        lines.append("📭 График за этот период ещё не составлен.")
        lines.append("Примерная зарплата недоступна.")
    else:
        lines.append("По графику смен: " + str(schedule_shifts))
        lines.append("Часов по графику (прим.): " + str(schedule_hours))
        if rate:
            approx_salary = round(schedule_hours * rate)
            lines.append("")
            lines.append("💰 Примерная зарплата: ~" + f"{approx_salary:,}".replace(",", " ") + " ₽")
            lines.append("   (" + str(rate) + " ₽/ч × " + str(schedule_hours) + " ч)")
        else:
            lines.append("")
            lines.append("⚠️ Ставка для твоей должности не указана")

    if track_hours:
        shifts = await get_shifts_for_month(user_id, year, month)
        shifts = [r for r in shifts if period_start <= int(str(r[0]).split("-")[2]) <= period_end]
        actual_hours = sum(float(r[1]) for r in shifts)
        lines.append("")
        lines.append("✅ Внесено смен: " + str(len(shifts)))
        lines.append("⏱ Часов внесено: " + fmt_hours(actual_hours))
        if rate and actual_hours > 0:
            actual_salary = round(actual_hours * rate)
            lines.append("💰 Зарплата по факту: ~" + f"{actual_salary:,}".replace(",", " ") + " ₽")

    return "\n".join(lines)


async def get_shift_history_period_shifts(
    user_id: int, year: int, month: int, start_day: int, end_day: int,
):
    shifts = await get_shifts_for_month(user_id, year, month)
    result = []

    for row in shifts:
        date_value = row[0]
        hours = row[1]
        shift_type = row[2] if len(row) > 2 else None
        is_standard = row[3] if len(row) > 3 else None
        note = row[4] if len(row) > 4 else None

        date_str = str(date_value)
        try:
            day = int(date_str.split("-")[-1])
        except Exception:
            continue

        if start_day <= day <= end_day:
            result.append((date_str, hours, shift_type, is_standard, note))

    return result


async def build_shift_history_text(
    user_id: int, year: int, month: int, start_day: int, end_day: int,
) -> str:
    period_shifts = await get_shift_history_period_shifts(
        user_id, year, month, start_day, end_day,
    )

    month_name = month_label(month)
    lines = [f"📋 История смен: {start_day}–{end_day} {month_name} {year}", ""]

    if not period_shifts:
        lines.append("За этот период смены не внесены.")
        return "\n".join(lines)

    total_hours = 0.0

    for date_str, hours, shift_type, is_standard, note in period_shifts:
        try:
            total_hours += float(hours)
        except Exception:
            pass

        shift_label = ""
        if shift_type == "morning":
            shift_label = "утро"
        elif shift_type == "evening":
            shift_label = "вечер"
        elif shift_type:
            shift_label = str(shift_type)

        std_label = ""
        try:
            if is_standard:
                std_label = " стандартная"
        except Exception:
            pass

        line = f"📅 {date_str} — {fmt_hours(hours)} ч"
        if shift_label:
            line += f" {shift_label}"
        if std_label:
            line += f" ({std_label.strip()})"
        if note:
            line += f" — {note}"

        lines.append(line)

    lines.append("")
    lines.append("Итого: " + fmt_hours(total_hours) + " ч")

    return "\n".join(lines)


def parse_salary_period_button(text: str, now) -> tuple[int, int, int, int] | None:
    """Парсит кнопку вида «1-15 Май» или «16-30 Июнь»."""
    parts = text.strip().split(" ", 1)
    period_part = parts[0]
    month_word = parts[1] if len(parts) > 1 else ""

    month_num = None
    for num in range(1, 13):
        if month_word == month_label(num):
            month_num = num
            break

    if not month_num:
        return None

    if month_num > now.month:
        year = now.year - 1
    else:
        year = now.year

    if period_part == "1-15":
        return year, month_num, 1, 15

    period_start = 16
    period_end = calendar.monthrange(year, month_num)[1]
    return year, month_num, period_start, period_end


async def lookup_shift_for_date(name: str, role: str | None, dt) -> tuple[str | None, float | None]:
    """Смена по графику на дату: (shift_type, standard_hours) или (None, None)."""
    if _find_row is None or _get_day_value is None:
        return None, None

    try:
        row, _ = await _find_row(name, dt.day, dt.month, dt.year, target_role=role)
        if row:
            value = await _get_day_value(row, dt.day, dt.month, dt.year)
            if is_work_shift(value):
                shift_type = detect_shift_type(value)
                standard_hours = get_standard_hours(shift_type, dt)
                return shift_type, standard_hours
    except (ValueError, ConnectionError):
        pass

    return None, None


def format_shift_entry_prompt(dt, shift_type, standard_hours, existing) -> str:
    date_label = dt.strftime("%d.%m.%Y")
    day_type = "выходной" if dt.weekday() in (4, 5) else "будний день"
    shift_label = {"morning": "утро", "evening": "вечер"}.get(shift_type or "", "")

    lines = [date_label + " (" + day_type + ")"]
    if shift_type:
        lines.append("По графику: " + shift_label + ", стандартная смена — " + str(standard_hours) + " ч")
    else:
        lines.append("Смены нет в графике или данные недоступны.")
    if existing:
        lines.append("")
        lines.append("✏️ Уже внесено: " + str(existing[1]) + " ч — можешь обновить.")
    return "\n".join(lines)
