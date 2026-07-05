"""Данные для Telegram Mini App."""

import calendar
from datetime import date, datetime, timedelta

from app_config import now_local
from departments_manager import (
    DEPARTMENTS,
    is_person_name,
    normalize_role_name,
    ordered_role_keys,
    person_has_ambiguous_role,
    role_display_label,
    roles_for_person,
)
from keyboards.compare import get_available_periods
from repositories.shifts_repo import delete_shift, get_shift_for_date, get_shifts_for_month, save_shift
from repositories.users_repo import get_user, save_user
from schedule_utils import detect_shift, detect_shift_type, format_date, get_standard_hours, is_work_shift
from ui_utils import is_valid_time
from services import salary_service
from services import schedule_service as schedule
from services.telegram_notify import send_user_message


WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
THEMES = {
    "alice_dark",
    "ruby_smoke",
    "ivory_noir",
    "emerald_lounge",
    "alice_cinema",
    "ivory_palace",
    "white_classic",
    "white_cinema",
    "white_rabbit",
    "red_queen_portrait",
    "caterpillar_cinema",
}


def current_period() -> tuple[int, int, int, int]:
    now = now_local()
    year, month, day = now.year, now.month, now.day
    if day <= 15:
        return year, month, 1, 15
    last = calendar.monthrange(year, month)[1]
    return year, month, 16, last


async def get_profile(user_id: int) -> dict:
    user = await get_user(user_id)
    if not user or not user[1]:
        return {"registered": False, "user_id": user_id}

    role = user[4] if len(user) > 4 else None
    track_hours = bool(user[5]) if len(user) > 5 else False
    notify_hours = bool(user[6]) if len(user) > 6 else False
    notify = bool(user[2]) if len(user) > 2 else False
    notify_time = user[3] if len(user) > 3 else None
    theme = user[8] if len(user) > 8 and user[8] else "alice_dark"
    role_label = role_display_label(role) if role else None

    return {
        "registered": True,
        "user_id": user_id,
        "name": user[1],
        "role": role,
        "role_label": role_label,
        "track_hours": track_hours,
        "notify": notify,
        "notify_time": notify_time,
        "notify_hours": notify_hours,
        "theme": theme,
    }


async def update_user_settings(
    user_id: int,
    *,
    notify: bool | None = None,
    notify_time: str | None = None,
    track_hours: bool | None = None,
    notify_hours: bool | None = None,
    theme: str | None = None,
) -> dict:
    user = await get_user(user_id)
    if not user or not user[1]:
        return {"error": "not_registered"}

    if notify_time is not None and not is_valid_time(notify_time):
        return {"error": "bad_time"}
    if theme is not None and theme not in THEMES:
        return {"error": "bad_theme"}

    chat_msgs: list[str] = []

    if notify is True:
        time_val = notify_time or user[3]
        if not time_val:
            return {"error": "need_time"}
        await save_user(user_id, notify=1, notify_time=time_val)
        chat_msgs.append(f"Уведомления включены 🔔\nВремя: {time_val}")
    elif notify is False:
        await save_user(user_id, notify=0)
        chat_msgs.append("Уведомления выключены 🔕")
    elif notify_time is not None:
        await save_user(user_id, notify_time=notify_time, notify=1)
        if notify_time != (user[3] or ""):
            chat_msgs.append(
                f"Время уведомлений сохранено: {notify_time}\nУведомления включены 🔔",
            )

    if track_hours is not None:
        await save_user(user_id, track_hours=1 if track_hours else 0)
    if notify_hours is not None:
        await save_user(user_id, notify_hours=1 if notify_hours else 0)
    if theme is not None:
        await save_user(user_id, theme=theme)

    for msg in chat_msgs:
        await send_user_message(user_id, msg)

    return await get_profile(user_id)


def list_departments() -> dict:
    departments = []
    for dep_label, names in DEPARTMENTS.items():
        role = dep_label.split(" ", 1)[-1] if " " in dep_label else dep_label
        departments.append({
            "role_label": dep_label,
            "role": role,
            "names": names,
        })
    return {"departments": departments}


async def update_profile(user_id: int, name: str, role: str) -> dict:
    if not is_person_name(name):
        return {"error": "bad_name"}
    valid_roles = roles_for_person(name)
    normalized_role = normalize_role_name(role)
    normalized_valid_roles = [normalize_role_name(item) for item in valid_roles]
    if normalized_role not in normalized_valid_roles:
        return {"error": "bad_role"}
    role_to_save = valid_roles[normalized_valid_roles.index(normalized_role)]
    await save_user(user_id, name=name, role=role_to_save)
    from services.schedule_watch_service import reset_user_snapshot
    await reset_user_snapshot(user_id)
    return await get_profile(user_id)


async def remove_shift_log(user_id: int, date_str: str) -> dict:
    user = await get_user(user_id)
    if not user or not user[1]:
        return {"error": "not_registered"}
    if not (user[5] if len(user) > 5 else 0):
        return {"error": "hours_disabled"}
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return {"error": "bad_date"}
    deleted = await delete_shift(user_id, date_str)
    if not deleted:
        return {"error": "not_found"}
    return {"ok": True, "date": date_str}


async def _shift_for_person(name: str, role: str | None, dt: datetime) -> dict:
    try:
        row, _ = await schedule.find_row(
            name, dt.day, dt.month, dt.year, target_role=role,
        )
        if not row:
            return {"working": False, "shift_type": None, "label": None, "hours": None}

        value = await schedule.get_day_value(row, dt.day, dt.month, dt.year)
        if not is_work_shift(value):
            return {"working": False, "shift_type": None, "label": "вых", "hours": None}

        shift_type = detect_shift_type(str(value) if value else "")
        std = get_standard_hours(shift_type, dt) if shift_type else None
        label = "утро" if shift_type == "morning" else "вечер" if shift_type == "evening" else "смена"
        return {
            "working": True,
            "shift_type": shift_type,
            "label": label,
            "hours": std,
            "raw": str(value).strip() if value else None,
        }
    except (ValueError, ConnectionError):
        return {"working": False, "shift_type": None, "label": None, "hours": None, "error": True}


async def _day_schedule_entry(
    name: str,
    role: str | None,
    dt: datetime,
    today: date,
) -> dict:
    shift = await _shift_for_person(name, role, dt)
    published = schedule.is_day_published(dt.day, dt.month, dt.year)
    return {
        "date": dt.strftime("%Y-%m-%d"),
        "weekday": WEEKDAYS_SHORT[dt.weekday()],
        "day": dt.day,
        "month": dt.month,
        "is_today": dt.date() == today,
        "published": published,
        **shift,
    }


async def _week_schedule_for(name: str, role: str | None, week_offset: int = 0) -> dict:
    now = now_local()
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0,
    ) + timedelta(weeks=week_offset)

    today = now.date()
    days = []
    for i in range(7):
        dt = week_start + timedelta(days=i)
        days.append(await _day_schedule_entry(name, role, dt, today))

    first, last = days[0], days[-1]
    if first["month"] == last["month"]:
        header = f"{first['day']}–{last['day']} {schedule.MONTHS[first['month']]}"
    else:
        header = f"{first['day']}–{last['day']}"

    today_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_dt = today_dt + timedelta(days=1)
    today_entry = await _day_schedule_entry(name, role, today_dt, today)
    tomorrow_entry = await _day_schedule_entry(name, role, tomorrow_dt, today)

    return {
        "name": name,
        "role": role,
        "role_label": role_display_label(role) if role else None,
        "header": header,
        "week_offset": week_offset,
        "today": today_entry,
        "tomorrow": tomorrow_entry,
        "days": days,
    }


async def get_week_schedule(user_id: int, week_offset: int = 0) -> dict:
    user = await get_user(user_id)
    if not user or not user[1]:
        return {"error": "not_registered"}

    return await _week_schedule_for(
        user[1], user[4] if len(user) > 4 else None, week_offset,
    )


async def get_month_schedule(user_id: int, month_offset: int = 0) -> dict:
    user = await get_user(user_id)
    if not user or not user[1]:
        return {"error": "not_registered"}

    return await _month_schedule_for(
        user[1], user[4] if len(user) > 4 else None, month_offset,
    )


async def _month_schedule_for(name: str, role: str | None, month_offset: int = 0) -> dict:
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
        shift = await _shift_for_person(name, role, dt)
        published = schedule.is_day_published(day, month, year)

        if shift["working"]:
            working += 1
        elif published and not shift.get("error"):
            off += 1

        days.append({
            "date": dt.strftime("%Y-%m-%d"),
            "day": day,
            "weekday": WEEKDAYS_SHORT[dt.weekday()],
            "is_today": dt.date() == today,
            "published": published,
            **shift,
        })

    first_weekday = datetime(year, month, 1, tzinfo=now.tzinfo).weekday()

    return {
        "name": name,
        "role": role,
        "role_label": role_display_label(role) if role else None,
        "year": year,
        "month": month,
        "month_name": schedule.MONTHS[month],
        "header": f"{schedule.MONTHS[month]} {year}",
        "month_offset": month_offset,
        "first_weekday": first_weekday,
        "days": days,
        "stats": {"working": working, "off": off},
    }


async def get_colleague_month(name: str, role: str | None, month_offset: int = 0) -> dict:
    return await _month_schedule_for(name, role, month_offset)


async def get_day_roster(date_str: str) -> dict:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=now_local().tzinfo)
    except ValueError:
        return {"error": "bad_date"}

    day, month, year = dt.day, dt.month, dt.year
    published = schedule.is_day_published(day, month, year)

    departments: list[dict] = []
    working_names: set[str] = set()
    if published:
        by_role = await schedule.get_people_for_day(day, month, year)
        for role_key in ordered_role_keys(by_role):
            people = by_role.get(role_key, [])
            if not people:
                continue
            working_names.update(people)
            departments.append({
                "role": role_key,
                "role_label": role_display_label(role_key),
                "people": people,
            })

    off_people: list[dict] = []
    if published:
        for dep_label, names in DEPARTMENTS.items():
            dep_role = dep_label.split(" ", 1)[-1] if " " in dep_label else dep_label
            for person_name in names:
                if person_name in working_names:
                    continue
                shift = await _shift_for_person(person_name, dep_role, dt)
                if shift.get("error") or shift["working"]:
                    continue
                off_people.append({
                    "name": person_name,
                    "role_label": role_display_label(dep_role),
                })

    off_people.sort(key=lambda p: (p["role_label"] or "", p["name"]))

    return {
        "date": date_str,
        "day": day,
        "month": month,
        "year": year,
        "weekday": WEEKDAYS_SHORT[dt.weekday()],
        "header": f"{day} {schedule.MONTHS[month]}",
        "published": published,
        "total_working": len(working_names),
        "departments": departments,
        "off": off_people,
    }


async def get_analytics(user_id: int) -> dict:
    user = await get_user(user_id)
    if not user or not user[1]:
        return {"error": "not_registered"}

    name = user[1]
    role = user[4] if len(user) > 4 else None
    year, month, p_start, p_end = current_period()

    morning = evening = off = 0
    schedule_hours = 0.0
    schedule_shifts = 0

    for day in range(p_start, p_end + 1):
        dt = datetime(year, month, day, tzinfo=now_local().tzinfo)
        shift = await _shift_for_person(name, role, dt)
        if shift.get("error"):
            continue
        if shift["working"]:
            schedule_shifts += 1
            if shift["shift_type"] == "morning":
                morning += 1
            elif shift["shift_type"] == "evening":
                evening += 1
            if shift["hours"]:
                schedule_hours += float(shift["hours"])
        else:
            off += 1

    logged_hours = 0.0
    track_hours = bool(user[5]) if len(user) > 5 else False
    today = now_local().date()
    past_shifts = past_logged = future_shifts = 0
    shift_log: list[dict] = []
    missing_past_days: list[str] = []

    if track_hours:
        shifts = await get_shifts_for_month(user_id, year, month)
        logged_by_day: dict[int, float] = {}
        for row in shifts:
            date_str, hours = str(row[0]), float(row[1])
            try:
                d = int(date_str.split("-")[2])
            except (ValueError, IndexError):
                continue
            if p_start <= d <= p_end:
                logged_by_day[d] = logged_by_day.get(d, 0) + hours
                logged_hours += hours

        for day in range(p_start, p_end + 1):
            dt = datetime(year, month, day, tzinfo=now_local().tzinfo)
            shift = await _shift_for_person(name, role, dt)
            if not shift["working"]:
                continue

            is_past = dt.date() <= today
            logged = day in logged_by_day
            entry = {
                "date": dt.strftime("%Y-%m-%d"),
                "day": day,
                "weekday": WEEKDAYS_SHORT[dt.weekday()],
                "shift_type": shift["shift_type"],
                "label": shift["label"],
                "is_past": is_past,
                "logged": logged,
                "hours": logged_by_day.get(day) if logged else shift.get("hours"),
            }
            shift_log.append(entry)

            if is_past:
                past_shifts += 1
                if logged:
                    past_logged += 1
                else:
                    missing_past_days.append(entry["date"])
            else:
                future_shifts += 1

    return {
        "period": {"year": year, "month": month, "start": p_start, "end": p_end},
        "shifts": schedule_shifts,
        "hours": round(schedule_hours, 1),
        "morning": morning,
        "evening": evening,
        "off": off,
        "track_hours": track_hours,
        "logged_hours": round(logged_hours, 1),
        "hours_status": {
            "past_shifts": past_shifts,
            "logged_shifts": past_logged,
            "future_shifts": future_shifts,
            "missing_past_days": missing_past_days,
            "shift_log": shift_log,
        },
    }


async def get_people_on_shift(user_id: int, day_offset: int = 0) -> dict:
    user = await get_user(user_id)
    if not user or not user[1]:
        return {"error": "not_registered"}

    name = user[1]
    role = user[4] if len(user) > 4 else None
    now = now_local()
    target = (now + timedelta(days=day_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
    day, month, year = target.day, target.month, target.year

    published = schedule.is_day_published(day, month, year)
    my_shift = await _shift_for_person(name, role, target)

    departments: list[dict] = []
    total = 0
    if published:
        by_role = await schedule.get_people_for_day(day, month, year)
        for role_key in ordered_role_keys(by_role):
            people = by_role.get(role_key, [])
            if not people:
                continue
            total += len(people)
            departments.append({
                "role": role_key,
                "role_label": role_display_label(role_key),
                "people": people,
            })

    return {
        "date": target.strftime("%Y-%m-%d"),
        "day": day,
        "month": month,
        "year": year,
        "weekday": WEEKDAYS_SHORT[target.weekday()],
        "header": f"{day} {schedule.MONTHS[month]}",
        "published": published,
        "total": total,
        "my_shift": my_shift,
        "departments": departments,
        "day_offset": day_offset,
    }


async def get_shift_day_info(user_id: int, date_str: str) -> dict:
    user = await get_user(user_id)
    if not user or not user[1]:
        return {"error": "not_registered"}

    if not user[5]:
        return {"error": "hours_disabled"}

    name = user[1]
    role = user[4] if len(user) > 4 else None
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=now_local().tzinfo)
    except ValueError:
        return {"error": "bad_date"}

    shift_type, standard_hours = await salary_service.lookup_shift_for_date(name, role, dt)
    existing = await get_shift_for_date(user_id, date_str)

    return {
        "date": date_str,
        "day": dt.day,
        "weekday": WEEKDAYS_SHORT[dt.weekday()],
        "header": f"{dt.day} {schedule.MONTHS[dt.month]}",
        "shift_type": shift_type,
        "shift_label": (
            "утро" if shift_type == "morning"
            else "вечер" if shift_type == "evening"
            else None
        ),
        "standard_hours": standard_hours,
        "logged_hours": float(existing[1]) if existing else None,
        "has_schedule_shift": shift_type is not None,
    }


async def log_shift_hours(
    user_id: int,
    date_str: str,
    hours: float,
    *,
    is_standard: bool = True,
) -> dict:
    user = await get_user(user_id)
    if not user or not user[1]:
        return {"error": "not_registered"}
    if not user[5]:
        return {"error": "hours_disabled"}

    if hours <= 0 or hours > 24:
        return {"error": "bad_hours"}

    name = user[1]
    role = user[4] if len(user) > 4 else None
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=now_local().tzinfo)
    except ValueError:
        return {"error": "bad_date"}

    shift_type, _ = await salary_service.lookup_shift_for_date(name, role, dt)
    await save_shift(
        user_id=user_id,
        date=date_str,
        hours=hours,
        shift_type=shift_type,
        is_standard=is_standard,
    )
    return {"ok": True, "date": date_str, "hours": round(hours, 2)}


async def get_salary(user_id: int, year: int | None = None, month: int | None = None,
                     period_start: int | None = None, period_end: int | None = None) -> dict:
    user = await get_user(user_id)
    if not user or not user[1]:
        return {"error": "not_registered"}

    if year is None or month is None or period_start is None or period_end is None:
        year, month, period_start, period_end = current_period()

    return await salary_service.build_salary_stats_data(
        user_id, user, year, month, period_start, period_end,
    )


def list_compare_periods() -> list[dict]:
    items = []
    for year, month, start_day, end_day in get_available_periods():
        items.append({
            "year": year,
            "month": month,
            "start": start_day,
            "end": end_day,
            "label": f"{start_day}–{end_day} {schedule.MONTHS[month]} {year}",
        })
    return items


async def get_colleagues(user_id: int) -> dict:
    user = await get_user(user_id)
    if not user or not user[1]:
        return {"error": "not_registered"}

    my_name = user[1]
    departments = []
    for dep_label, names in DEPARTMENTS.items():
        role = dep_label.split(" ", 1)[-1] if " " in dep_label else dep_label
        people = [{"name": n, "role": role} for n in names if n != my_name]
        if people:
            departments.append({
                "role_label": dep_label,
                "role": role,
                "people": people,
            })
    return {"departments": departments}


async def get_colleague_week(name: str, role: str | None, week_offset: int = 0) -> dict:
    return await _week_schedule_for(name, role, week_offset)


async def compare_with_colleagues(
    user_id: int,
    colleagues: list[dict],
    year: int,
    month: int,
    period_start: int,
    period_end: int,
) -> dict:
    user = await get_user(user_id)
    if not user or not user[1]:
        return {"error": "not_registered"}

    my_name = user[1]
    my_role = user[4] if len(user) > 4 else None
    roster = [(my_name, my_role)] + [(c["name"], c.get("role")) for c in colleagues]

    common_work: list[dict] = []
    common_off: list[dict] = []

    for day in range(period_start, period_end + 1):
        values: dict[str, object] = {}
        for name, role in roster:
            target_role = role
            row = None
            try:
                row, _ = await schedule.find_row(
                    name, day, month, year, target_role=target_role,
                )
            except (ValueError, ConnectionError):
                pass

            if not row and target_role and not person_has_ambiguous_role(name):
                try:
                    row, _ = await schedule.find_row(
                        name, day, month, year, target_role=None,
                    )
                except (ValueError, ConnectionError):
                    pass

            if not row:
                values = {}
                break

            values[name] = await schedule.get_day_value(row, day, month, year)

        if len(values) != len(roster):
            continue

        if all(is_work_shift(v) for v in values.values()):
            common_work.append({
                "day": day,
                "date": format_date(day, month, year),
                "shifts": {name: detect_shift(values[name]) for name in values},
            })
        elif all(not is_work_shift(v) for v in values.values()):
            common_off.append({
                "day": day,
                "date": format_date(day, month, year),
            })

    participants = [
        {"name": my_name, "role_label": role_display_label(my_role) if my_role else None},
    ]
    for c in colleagues:
        role = c.get("role")
        participants.append({
            "name": c["name"],
            "role_label": role_display_label(role) if role else None,
        })

    return {
        "period": {
            "year": year,
            "month": month,
            "start": period_start,
            "end": period_end,
            "label": f"{period_start}–{period_end} {schedule.MONTHS[month]} {year}",
        },
        "participants": participants,
        "common_work": common_work,
        "common_off": common_off,
    }


async def _person_period_stats(name: str, role: str | None, year: int, month: int, p_start: int, p_end: int) -> dict:
    shifts = 0
    hours = 0.0
    for day in range(p_start, p_end + 1):
        dt = datetime(year, month, day, tzinfo=now_local().tzinfo)
        shift = await _shift_for_person(name, role, dt)
        if shift["working"]:
            shifts += 1
            if shift["hours"]:
                hours += float(shift["hours"])
    return {"name": name, "shifts": shifts, "hours": round(hours, 1)}


async def get_team_analytics() -> dict:
    year, month, p_start, p_end = current_period()
    rows = []

    for dep_label, names in DEPARTMENTS.items():
        role = dep_label.split(" ", 1)[-1] if " " in dep_label else dep_label
        for name in names:
            stats = await _person_period_stats(name, role, year, month, p_start, p_end)
            if stats["shifts"] > 0:
                rows.append({**stats, "role": role})

    rows.sort(key=lambda r: (-r["hours"], r["name"]))

    coverage = []
    for day in range(p_start, min(p_end, p_start + 6) + 1):
        people = await schedule.get_people_for_day(day, month, year)
        waiters = len(people.get("Официант", []))
        coverage.append({
            "day": day,
            "label": WEEKDAYS_SHORT[datetime(year, month, day).weekday()],
            "waiters": waiters,
            "thin": waiters < 3,
        })

    thin_days = [c for c in coverage if c["thin"]]

    return {
        "period": {"year": year, "month": month, "start": p_start, "end": p_end},
        "team": rows[:20],
        "coverage": coverage,
        "thin_days": thin_days,
    }
