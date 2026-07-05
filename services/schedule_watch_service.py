"""Отслеживание изменений графика в Google Sheets и уведомления в чат."""

import json
import logging
from datetime import datetime, timedelta

from app_config import now_local
from keyboards.inline_miniapp import schedule_change_reply_markup
from repositories.schedule_snapshots_repo import delete_snapshot, get_snapshot, save_snapshot
from repositories.users_repo import get_registered_users
from schedule_utils import WEEKDAYS, detect_shift, detect_shift_type, is_work_shift
from services import schedule_service as schedule
from services.telegram_notify import send_user_message

WATCH_DAYS = 45
MONTHS = None
_UNRELIABLE_STATES = frozenset({"error", "missing"})


def configure_schedule_watch(months):
    global MONTHS
    MONTHS = months


def _is_work(state: str) -> bool:
    return state.startswith("work|")


def _human_state(state: str) -> str:
    if state == "off":
        return "выходной"
    if state == "unpublished":
        return "график не опубликован"
    if state.startswith("work|"):
        parts = state.split("|", 2)
        if len(parts) >= 3 and parts[2]:
            return parts[2]
        return "смена"
    return state


async def day_state(name: str, role: str | None, dt: datetime) -> str:
    day, month, year = dt.day, dt.month, dt.year
    if not schedule.is_day_published(day, month, year):
        return "unpublished"
    try:
        row, _ = await schedule.find_row(name, day, month, year, target_role=role)
    except (ValueError, ConnectionError):
        return "error"
    if not row:
        return "missing"
    value = await schedule.get_day_value(row, day, month, year)
    if not is_work_shift(value):
        return "off"
    shift_type = detect_shift_type(str(value) if value else "") or ""
    label = detect_shift(str(value) if value else "") or "смена"
    return f"work|{shift_type}|{label}"


async def build_snapshot(name: str, role: str | None) -> dict[str, str]:
    snap: dict[str, str] = {}
    now = now_local()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for i in range(WATCH_DAYS):
        dt = start + timedelta(days=i)
        key = dt.strftime("%Y-%m-%d")
        snap[key] = await day_state(name, role, dt)
    return snap


def diff_snapshots(old: dict, new: dict) -> list[tuple[str, datetime, str, str]]:
    """Сравнивает только даты, присутствующие в обоих снимках."""
    changes = []
    common_dates = set(old.keys()) & set(new.keys())
    tz = now_local().tzinfo
    today = now_local().replace(hour=0, minute=0, second=0, microsecond=0)

    for date_str in sorted(common_dates):
        old_val = old[date_str]
        new_val = new[date_str]
        if old_val == new_val:
            continue

        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)

        if _is_work(old_val) and not _is_work(new_val):
            if new_val in _UNRELIABLE_STATES:
                continue
            if dt < today:
                continue
            changes.append(("removed", dt, old_val, new_val))
        elif not _is_work(old_val) and _is_work(new_val):
            if old_val in _UNRELIABLE_STATES:
                continue
            changes.append(("added", dt, old_val, new_val))
        elif _is_work(old_val) and _is_work(new_val):
            changes.append(("changed", dt, old_val, new_val))

    return changes


def _format_change(kind: str, dt: datetime, old: str, new: str) -> str:
    months = MONTHS or schedule.MONTHS
    wd = WEEKDAYS[dt.weekday()]
    dlabel = f"{wd} {dt.day} {months[dt.month]}"
    if kind == "removed":
        return f"❌ Снята смена — {dlabel}\n   было: {_human_state(old)}"
    if kind == "added":
        return f"✅ Добавлена смена — {dlabel}\n   {_human_state(new)}"
    return f"🔄 Изменена смена — {dlabel}\n   было: {_human_state(old)} → {_human_state(new)}"


async def check_user_schedule(user_id: int, name: str, role: str | None) -> None:
    new_snap = await build_snapshot(name, role)
    old_raw = await get_snapshot(user_id)
    if old_raw is None:
        await save_snapshot(user_id, new_snap)
        return

    old_snap = json.loads(old_raw)
    changes = diff_snapshots(old_snap, new_snap)
    if not changes:
        await save_snapshot(user_id, new_snap)
        return

    lines = ["📋 Изменения в твоём графике:", ""]
    for item in changes[:8]:
        lines.append(_format_change(*item))
    if len(changes) > 8:
        lines.append(f"\n…и ещё {len(changes) - 8}")

    ok = await send_user_message(
        user_id,
        "\n".join(lines),
        reply_markup=schedule_change_reply_markup(),
    )
    if ok:
        await save_snapshot(user_id, new_snap)
    else:
        logging.warning(
            "schedule_watch: уведомление не доставлено, snapshot сохранён user_id=%s name=%s",
            user_id,
            name,
        )


async def check_all_registered_users() -> None:
    users = await get_registered_users()
    for user_id, name, role in users:
        try:
            await check_user_schedule(user_id, name, role)
        except Exception:
            logging.exception("schedule_watch: user_id=%s name=%s", user_id, name)


async def reset_user_snapshot(user_id: int) -> None:
    await delete_snapshot(user_id)
