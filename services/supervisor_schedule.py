"""Фиксированный недельный график управляющего (не из Google Sheets).

Коммит dfbe8f0 на GitHub main пока отсутствует; этот модуль восстановлен
с Fly prod (work-schedule-bot). Часы не выводить из таблицы официантов.
"""

from __future__ import annotations

import calendar
import copy
import json
import re
from datetime import date, datetime, timedelta

from app_config import now_local
from services.gen_cleaning_service import is_gen_cleaning_day

WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

SUPERVISOR_ROLE = "Управляющий"
SUPERVISOR_DEPARTMENT_LABEL = "👤 Управляющий"

# Расширяемый шаблон: weekday 0=пн … 6=вс.
DEFAULT_FIXED_SCHEDULE: dict = {
    "version": 2,
    "week": [
        {
            "weekday": 0,
            "blocks": [{"kind": "shift", "start": "11:00", "end": "19:00"}],
        },
        {
            "weekday": 1,
            "blocks": [
                {
                    "kind": "meeting",
                    "start": "11:00",
                    "end": "13:00",
                    "title": "собрание",
                },
                {"kind": "shift", "start": "16:00", "end": "19:00"},
            ],
        },
        {
            "weekday": 2,
            "blocks": [{"kind": "shift", "start": "11:00", "end": "19:00"}],
        },
        {"weekday": 3, "blocks": []},
        {
            "weekday": 4,
            "blocks": [{"kind": "shift", "start": "16:00", "end": "01:00"}],
        },
        {
            "weekday": 5,
            "blocks": [{"kind": "shift", "start": "16:00", "end": "01:00"}],
        },
        {"weekday": 6, "blocks": []},
    ],
}

MEETING_REMINDER_WEEKDAY = 0  # понедельник
MEETING_REMINDER_TIME = "22:00"
MEETING_REMINDER_TEXT = (
    "🔔 Не забудь завтра собрание\n\n"
    "Вторник · 11:00–13:00"
)


def is_supervisor_role(role: str | None) -> bool:
    if not role:
        return False
    text = str(role).replace("\xa0", " ").strip()
    # «👤 Управляющий» / «👑 Управляющий»
    if " " in text and not text.split(" ", 1)[0].isalpha():
        text = text.split(" ", 1)[1].strip()
    from departments_manager import normalize_role_name
    normalized = (normalize_role_name(text) or text).strip().lower()
    return normalized in {"управляющий", "управляющие"}


def is_supervisor_account(account_type: str | None) -> bool:
    return (account_type or "staff").strip().lower() == "supervisor"


def uses_fixed_schedule(name: str | None, role: str | None = None) -> bool:
    """Личный график управляющего — код, не Google Sheets.

    Не путать с официантом «Владислав»: имя должно быть в SUPERVISOR_NAMES
    или роль — Управляющий.
    """
    from app_config import is_supervisor_name
    return is_supervisor_name(name) or is_supervisor_role(role)


def resolve_fixed_schedule(raw) -> dict:
    """Достаёт шаблон из JSONB / dict / строки; иначе дефолт.

    Старые сохранённые шаблоны (version < текущего) игнорируем —
    часы задаются в коде и обновляются деплоем.
    """
    data = raw
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
    if isinstance(data, dict) and isinstance(data.get("week"), list):
        try:
            stored_ver = int(data.get("version") or 0)
        except (TypeError, ValueError):
            stored_ver = 0
        if stored_ver >= int(DEFAULT_FIXED_SCHEDULE.get("version") or 1):
            return data
    return copy.deepcopy(DEFAULT_FIXED_SCHEDULE)


def _block_time_label(block: dict) -> str:
    start = block.get("start") or ""
    end = block.get("end") or ""
    if start and end:
        return f"{start}–{end}"
    return start or end or ""


def _enrich_blocks(blocks: list[dict]) -> list[dict]:
    enriched = []
    for block in blocks:
        kind = block.get("kind") or "shift"
        title = block.get("title")
        if not title:
            title = "собрание" if kind == "meeting" else "смена"
        time_label = _block_time_label(block)
        label = f"{title} {time_label}".strip() if time_label else title
        enriched.append({
            "kind": kind,
            "title": title,
            "start": block.get("start"),
            "end": block.get("end"),
            "time": time_label or None,
            "label": label,
        })
    return enriched


def _day_label(blocks: list[dict]) -> str | None:
    if not blocks:
        return "вых"
    if len(blocks) == 1:
        return blocks[0]["label"]
    return " · ".join(b["label"] for b in blocks)


def _start_hour(block: dict) -> int | None:
    start = block.get("start") or ""
    m = re.match(r"(\d{1,2})", str(start))
    return int(m.group(1)) if m else None


def _shift_type_from_blocks(blocks: list[dict]) -> str | None:
    """Тип смены по часу начала: <14 = утро (в т.ч. 11:00–19:00)."""
    hours = [
        h for b in blocks
        if (b.get("kind") or "shift") == "shift"
        for h in [_start_hour(b)]
        if h is not None
    ]
    if not hours:
        return None
    types = ["morning" if h < 14 else "evening" for h in hours]
    if all(t == "morning" for t in types):
        return "morning"
    if all(t == "evening" for t in types):
        return "evening"
    return None


def shift_for_weekday(weekday: int, schedule: dict | None = None) -> dict:
    tmpl = resolve_fixed_schedule(schedule)
    by_wd = {
        int(item["weekday"]): item.get("blocks") or []
        for item in tmpl.get("week", [])
        if "weekday" in item
    }
    raw_blocks = by_wd.get(weekday, [])
    blocks = _enrich_blocks(raw_blocks)
    working = bool(blocks)
    return {
        "working": working,
        "shift_type": _shift_type_from_blocks(blocks) if working else None,
        "label": _day_label(blocks),
        "hours": None,
        "counts_hours": False,
        "in_roster": True,
        "blocks": blocks,
        "raw": None,
    }


def day_entry(dt: datetime, today: date, schedule: dict | None = None) -> dict:
    shift = shift_for_weekday(dt.weekday(), schedule)
    return {
        "date": dt.strftime("%Y-%m-%d"),
        "weekday": WEEKDAYS_SHORT[dt.weekday()],
        "day": dt.day,
        "month": dt.month,
        "is_today": dt.date() == today,
        "published": True,
        "gen_cleaning": is_gen_cleaning_day(dt.date()),
        **shift,
    }


def week_schedule(
    name: str,
    role: str | None,
    week_offset: int = 0,
    schedule: dict | None = None,
    *,
    months: dict | None = None,
) -> dict:
    from services import schedule_service as schedule_svc

    month_names = months or schedule_svc.MONTHS
    now = now_local()
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0,
    ) + timedelta(weeks=week_offset)
    today = now.date()
    days = [day_entry(week_start + timedelta(days=i), today, schedule) for i in range(7)]
    first, last = days[0], days[-1]
    if first["month"] == last["month"]:
        header = f"{first['day']}–{last['day']} {month_names[first['month']]}"
    else:
        header = f"{first['day']}–{last['day']}"

    today_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_dt = today_dt + timedelta(days=1)
    from departments_manager import role_display_label

    return {
        "name": name,
        "role": role,
        "role_label": role_display_label(role) if role else None,
        "header": header,
        "week_offset": week_offset,
        "today": day_entry(today_dt, today, schedule),
        "tomorrow": day_entry(tomorrow_dt, today, schedule),
        "days": days,
        "fixed_schedule": True,
    }


def month_schedule(
    name: str,
    role: str | None,
    month_offset: int = 0,
    schedule: dict | None = None,
    *,
    months: dict | None = None,
) -> dict:
    from services import schedule_service as schedule_svc
    from departments_manager import role_display_label

    month_names = months or schedule_svc.MONTHS
    now = now_local()
    month = now.month + month_offset
    year = now.year
    while month < 1:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1

    last_day = calendar.monthrange(year, month)[1]
    today = now.date()
    days = []
    working = off = 0
    for day in range(1, last_day + 1):
        dt = datetime(year, month, day, tzinfo=now.tzinfo)
        entry = day_entry(dt, today, schedule)
        if entry["working"]:
            working += 1
        else:
            off += 1
        days.append(entry)

    return {
        "name": name,
        "role": role,
        "role_label": role_display_label(role) if role else None,
        "year": year,
        "month": month,
        "month_name": month_names[month],
        "header": f"{month_names[month]} {year}",
        "month_offset": month_offset,
        "first_weekday": datetime(year, month, 1, tzinfo=now.tzinfo).weekday(),
        "days": days,
        "stats": {"working": working, "off": off},
        "fixed_schedule": True,
    }


async def team_digest_text(location_name: str | None = None) -> str | None:
    """Утренний дайджест «кто сегодня на смене» для supervisor."""
    from departments_manager import ordered_role_keys, role_display_label
    from schedule_utils import format_date
    from services import schedule_service as schedule

    now = now_local()
    day, month, year = now.day, now.month, now.year
    place = location_name or "Alice"

    if not schedule.is_day_published(day, month, year):
        return (
            f"🔔 Кто сегодня на смене\n\n"
            f"{place}\n"
            f"{format_date(day, month, year)}\n"
            f"📭 График пока не составлен"
        )

    people_by_role = await schedule.get_people_for_day(day, month, year)
    total = sum(len(v) for v in people_by_role.values())
    lines = [
        "🔔 Кто сегодня на смене",
        "",
        place,
        format_date(day, month, year),
        f"👥 На смене: {total} чел.",
    ]
    if not total:
        lines.append("\nСегодня никого в графике.")
        return "\n".join(lines)

    for role_key in ordered_role_keys(people_by_role):
        people = people_by_role.get(role_key) or []
        if not people:
            continue
        lines.append("")
        lines.append(role_display_label(role_key))
        for person in people:
            lines.append(f"• {person}")
    return "\n".join(lines)
