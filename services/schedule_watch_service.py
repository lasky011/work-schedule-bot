"""Отслеживание изменений графика в Google Sheets и уведомления в чат."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
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
_REPEAT_WINDOW = timedelta(minutes=12)
_REPEAT_ALERT_THRESHOLD = 2

# Последний отправленный diff: не повторяем тот же набор изменений.
_last_notified_fp: dict[int, str] = {}
# Время пушей для ловли зацикливания (в памяти процесса).
_recent_notifies: dict[int, list[datetime]] = defaultdict(list)
_repeat_alerted: set[int] = set()


def configure_schedule_watch(months):
    global MONTHS
    MONTHS = months


def reset_watch_runtime_state() -> None:
    """Для тестов: сбрасывает дедуп и счётчики повторов."""
    _last_notified_fp.clear()
    _recent_notifies.clear()
    _repeat_alerted.clear()


def _is_work(state: str) -> bool:
    return str(state).startswith("work|")


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


def parse_snapshot(raw) -> dict[str, str]:
    """snapshot в БД может быть TEXT (str) или уже dict (jsonb / psycopg2)."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        data = raw
    else:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            logging.warning("schedule_watch: не удалось разобрать snapshot")
            return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def merge_snapshot(old: dict[str, str], new: dict[str, str]) -> dict[str, str]:
    """Окно дат берём из new, но missing/error не затирают уже известный день.

    Иначе цикл такой: work→missing (молчим и сохраняем missing) →
    missing→work (пуш «добавлена смена») → снова missing → бесконечно.
    """
    merged: dict[str, str] = {}
    for key, new_val in new.items():
        old_val = old.get(key)
        if (
            new_val in _UNRELIABLE_STATES
            and old_val
            and old_val not in _UNRELIABLE_STATES
        ):
            merged[key] = old_val
            continue
        merged[key] = new_val
    return merged


def change_fingerprint(changes: list[tuple[str, datetime, str, str]]) -> str:
    parts = []
    for kind, dt, old, new in changes:
        day = dt.date().isoformat() if hasattr(dt, "date") else str(dt)
        parts.append(f"{kind}|{day}|{old}|{new}")
    return "\n".join(parts)


async def day_state(
    name: str,
    role: str | None,
    dt: datetime,
    alt_names: list[str] | None = None,
) -> str:
    day, month, year = dt.day, dt.month, dt.year
    if not schedule.is_day_published(day, month, year):
        return "unpublished"
    try:
        row, _ = await schedule.find_row(
            name, day, month, year, target_role=role, alt_names=alt_names,
        )
    except TypeError:
        row, _ = await schedule.find_row(
            name, day, month, year, target_role=role,
        )
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


async def build_snapshot(
    name: str,
    role: str | None,
    alt_names: list[str] | None = None,
) -> dict[str, str]:
    snap: dict[str, str] = {}
    now = now_local()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for i in range(WATCH_DAYS):
        dt = start + timedelta(days=i)
        key = dt.strftime("%Y-%m-%d")
        snap[key] = await day_state(name, role, dt, alt_names=alt_names)
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
            # Sheet glitch / rename miss: don't spam «снята смена».
            if new_val in _UNRELIABLE_STATES:
                continue
            if dt < today:
                continue
            changes.append(("removed", dt, old_val, new_val))
        elif not _is_work(old_val) and _is_work(new_val):
            # Только error — сбой загрузки. missing/unpublished → work
            # это новый период или смена имени: один пуш, потом snapshot.
            if old_val == "error":
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


async def _aliases_for(user_id: int) -> list[str]:
    try:
        from repositories.name_rename_repo import list_aliases
        return await list_aliases(user_id)
    except Exception:
        logging.warning("schedule_watch: aliases unavailable user_id=%s", user_id, exc_info=True)
        return []


def _trim_recent(user_id: int, now: datetime) -> list[datetime]:
    cutoff = now - _REPEAT_WINDOW
    kept = [ts for ts in _recent_notifies[user_id] if ts >= cutoff]
    _recent_notifies[user_id] = kept
    return kept


async def _alert_watch_repeat(user_id: int, name: str, n_changes: int) -> None:
    if user_id in _repeat_alerted:
        return
    _repeat_alerted.add(user_id)
    logging.error(
        "schedule_watch: LOOP user_id=%s name=%s n_changes=%s window=%s",
        user_id, name, n_changes, _REPEAT_WINDOW,
    )
    try:
        from repositories.admin_log_repo import record_action
        await record_action(
            0,
            "watch_repeat",
            f"user_id={user_id}, name={name}, n_changes={n_changes}",
        )
    except Exception:
        logging.exception("schedule_watch: не удалось записать watch_repeat")
    try:
        from services.admin_notify import notify_admins
        await notify_admins(
            "🚨 schedule_watch зациклился\n\n"
            f"Пользователь: {name or '—'}\n"
            f"user_id: `{user_id}`\n"
            f"Повторный пуш об изменениях графика за {_REPEAT_WINDOW.seconds // 60} мин.\n\n"
            "Снимок закреплён, повторный пуш этому человеку остановлен.\n"
            "Проверь имя/алиасы и при необходимости сбрось snapshot в карточке."
        )
    except Exception:
        logging.exception("schedule_watch: не удалось отправить alert о цикле")


async def check_user_schedule(user_id: int, name: str, role: str | None) -> None:
    alts = await _aliases_for(user_id)
    new_snap = await build_snapshot(name, role, alt_names=alts)
    old_raw = await get_snapshot(user_id)
    if old_raw is None:
        await save_snapshot(user_id, new_snap)
        return

    old_snap = parse_snapshot(old_raw)
    changes = diff_snapshots(old_snap, new_snap)
    to_save = merge_snapshot(old_snap, new_snap)

    if not changes:
        await save_snapshot(user_id, to_save)
        return

    fp = change_fingerprint(changes)
    now = now_local()
    recent = _trim_recent(user_id, now)

    # Тот же diff уже уходил — не спамим, только закрепляем снимок.
    if _last_notified_fp.get(user_id) == fp:
        logging.warning(
            "schedule_watch: повтор diff, snapshot закреплён без пуша user_id=%s name=%s n=%s",
            user_id, name, len(changes),
        )
        await save_snapshot(user_id, to_save)
        await _alert_watch_repeat(user_id, name, len(changes))
        return

    if len(recent) >= _REPEAT_ALERT_THRESHOLD:
        await save_snapshot(user_id, to_save)
        _last_notified_fp[user_id] = fp
        await _alert_watch_repeat(user_id, name, len(changes))
        return

    lines = ["📋 Изменения в твоём графике:", ""]
    for item in changes[:8]:
        lines.append(_format_change(*item))
    if len(changes) > 8:
        lines.append(f"\n…и ещё {len(changes) - 8}")

    kinds = ",".join(sorted({c[0] for c in changes}))
    logging.info(
        "schedule_watch: notify user_id=%s name=%s n=%s kinds=%s",
        user_id, name, len(changes), kinds,
    )

    ok = await send_user_message(
        user_id,
        "\n".join(lines),
        reply_markup=schedule_change_reply_markup(),
    )
    # Снимок всегда сохраняем: иначе при любом сбое Telegram цикл повторит
    # «добавлены смены» каждые 3 минуты, пока человек не перевыберет имя.
    _last_notified_fp[user_id] = fp
    _recent_notifies[user_id].append(now)
    await save_snapshot(user_id, to_save)
    if not ok:
        logging.warning(
            "schedule_watch: уведомление не доставлено, snapshot всё равно сохранён "
            "user_id=%s name=%s",
            user_id,
            name,
        )


async def check_all_registered_users() -> None:
    users = await get_registered_users()
    for row in users:
        user_id, name, role = row[0], row[1], row[2]
        try:
            await check_user_schedule(user_id, name, role)
        except Exception:
            logging.exception("schedule_watch: user_id=%s name=%s", user_id, name)


async def reset_user_snapshot(user_id: int) -> None:
    _last_notified_fp.pop(user_id, None)
    _recent_notifies.pop(user_id, None)
    _repeat_alerted.discard(user_id)
    await delete_snapshot(user_id)
