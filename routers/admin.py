"""Админ-команды и интерфейс admin-бота."""

import asyncio
import calendar
import logging
import re
from datetime import date
from typing import Awaitable, Callable

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app_config import APP_TIMEZONE_NAME, BOT_TOKEN, MINIAPP_URL, is_admin, now_local
from constants import SHIFT_END_NOTIFY
from db import get_db_connection
from keyboards.admin import (
    BTN_ADD_PERIOD,
    BTN_ALERTS,
    BTN_BROADCAST,
    BTN_CACHE,
    BTN_CANCEL,
    BTN_DASHBOARD,
    BTN_HELP,
    BTN_MONITOR,
    BTN_RECONCILE,
    BTN_PERIODS,
    BTN_RELOAD_PERIODS,
    BTN_RELOAD_SHEETS,
    BTN_RATES,
    BTN_STATS,
    BTN_LOGS,
    BTN_STATUS,
    BTN_USER_LOOKUP,
    BTN_USERS,
    CB_BROADCAST_CONFIRM,
    CB_BC_FORMAT,
    CB_BC_AUDIENCE,
    CB_CANCEL,
    BC_AUDIENCE_LABELS,
    BC_FMT_HTML,
    BC_FMT_HTML_MINIAPP,
    BC_FMT_LABELS,
    BC_FMT_PLAIN,
    CB_CONFIRM_DELETE,
    CB_DELETE_PERIOD,
    CB_EDIT_PERIOD,
    CB_EDIT_RATE,
    CB_RECONCILE,
    CB_RELOAD_PERIODS,
    CB_RELOAD_SHEETS,
    CB_USER_CHECK,
    CB_USER_OPEN,
    CB_USER_RESET_SNAP,
    CB_USER_TEST,
    add_period_half_kb,
    add_period_month_kb,
    admin_cancel_kb,
    admin_main_kb,
    broadcast_audience_kb,
    broadcast_confirm_kb,
    broadcast_format_kb,
    confirm_delete_kb,
    monitor_kb,
    periods_inline_kb,
    rates_inline_kb,
    stats_month_kb,
    user_card_kb,
    user_pick_kb,
)
from departments_manager import get_departments_status
from keyboards.inline_miniapp import miniapp_broadcast_markup
from repositories.admin_log_repo import list_recent_logs, record_action
from repositories.admin_repo import (
    get_broadcast_recipients,
    get_dashboard_stats,
    get_shift_stats,
    get_user_recent_shifts,
    get_watch_monitor_stats,
    list_track_hours_users,
    list_users,
    search_users,
)
from repositories.schedule_snapshots_repo import get_snapshot_meta
from repositories.shifts_repo import get_shifts_for_month
from repositories.users_repo import get_user
from schedule_utils import is_work_shift
from services.admin_alerts_service import run_health_alerts
from services import schedule_service as schedule
from services.schedule_watch_service import WATCH_DAYS, check_user_schedule, reset_user_snapshot
from services.telegram_notify import send_user_message
from services.sheet_periods_service import SHEET_GID_MAP, add_period, reload_from_db, remove_period
from services.rates_service import (
    bump_rates_signal,
    format_rates_text,
    reload_from_db as reload_rates_from_db,
    role_label,
    set_rate,
)
from services.cache_signal_service import bump_sheet_cache_signal
from services.period_coverage_service import format_period_key, missing_period_keys
from services.sheet_loader import load_all_sheet_gids
from sheets_client import cached_df, cached_time, clear_sheet_cache
from states import (
    AdminAddPeriodStates,
    AdminBroadcastStates,
    AdminEditPeriodStates,
    AdminRatesStates,
    AdminStatsStates,
    AdminUserLookupStates,
)
from ui_utils import fmt_hours, month_label

router = Router(name="admin")

_load_full_sheet: Callable[[], Awaitable] | None = None

_MONTH_YEAR_RE = re.compile(r"^(.+?)\s+(\d{4})$")
_HALF_FIRST_RE = re.compile(r"^1–15\s+")
_HALF_SECOND_RE = re.compile(r"^16–\d+\s+")

_ACTION_LABELS = {
    "save_period": "💾 период",
    "delete_period": "🗑 период",
    "reload_periods": "🔄 периоды",
    "reload_sheets": "🔄 листы",
    "broadcast": "📢 рассылка",
    "user_test_notify": "📨 тест",
    "user_reset_snapshot": "🔄 snapshot",
    "user_check_schedule": "👁 график",
    "reconcile_shifts": "⚖️ сверка",
    "health_check": "🔔 проверка",
    "update_rate": "💰 ставка",
}


def _hours_notify_times_text() -> str:
    return " / ".join(sorted(set(SHIFT_END_NOTIFY.values())))


def _main_cache_pickup_hint() -> str:
    return "Основной бот (prod/test) подхватит в течение ~3 мин."


def configure_admin_router(load_full_sheet):
    global _load_full_sheet
    _load_full_sheet = load_full_sheet


def _deny(message: Message) -> bool:
    return not is_admin(message.from_user.id)


async def _deny_callback(callback: CallbackQuery) -> bool:
    if is_admin(callback.from_user.id):
        return False
    await callback.answer("⛔ Нет доступа", show_alert=True)
    return True


def _period_end_day(year: int, month: int, start_day: int) -> int:
    if start_day == 1:
        return 15
    return calendar.monthrange(year, month)[1]


def _period_status_label(year: int, month: int, start_day: int, end_day: int) -> str:
    today = now_local().date()
    start = date(year, month, start_day)
    end = date(year, month, end_day)
    if today < start:
        return "будущий"
    if today > end:
        return "прошёл"
    return "актуален"


def _format_periods_text() -> str:
    lines = ["📅 Периоды графика\n"]
    for year, month, start_day in sorted(SHEET_GID_MAP.keys()):
        end_day = _period_end_day(year, month, start_day)
        status = _period_status_label(year, month, start_day, end_day)
        gid = SHEET_GID_MAP[(year, month, start_day)]
        lines.append(
            f"{start_day}–{end_day} {month_label(month)} {year}: gid={gid} ({status})"
        )
    if len(lines) == 1:
        lines.append("Периодов пока нет.")
    return "\n".join(lines)


def _format_snapshot_status(meta: tuple[str, object] | None) -> str:
    if not meta:
        return "нет (уведомления об изменениях не придут)"
    updated = meta[1]
    if updated is None:
        return "есть"
    if hasattr(updated, "strftime"):
        return f"есть, обновлён {updated.strftime('%Y-%m-%d %H:%M')}"
    return f"есть, обновлён {updated}"


async def _format_user_card(user_id: int) -> str:
    user = await get_user(user_id)
    if not user:
        return f"⚠️ Пользователь `{user_id}` не найден."

    _, name, notify, notify_time, role, track_hours, notify_hours, _notify_hours_time, theme = user
    meta = await get_snapshot_meta(user_id)
    recent = await get_user_recent_shifts(user_id)

    lines = [
        "🔍 Карточка пользователя\n",
        f"Имя: {name or '—'}",
        f"ID: `{user_id}`",
        f"Роль: {role or '—'}",
        f"Тема Mini App: {theme or '—'}",
        f"🔔 Смены: {'вкл ' + (notify_time or '?') if notify else 'выкл'}",
        f"⏱ Напоминания часов: {'вкл' if notify_hours else 'выкл'}",
        f"   Расписание: {_hours_notify_times_text()} (по типу смены)",
        f"📝 Учёт часов: {'вкл' if track_hours else 'выкл'}",
        f"Snapshot: {_format_snapshot_status(meta)}",
    ]

    if recent:
        lines.append("\nПоследние смены в БД:")
        for shift_date, hours in recent:
            d = shift_date.day if hasattr(shift_date, "day") else shift_date
            m = shift_date.month if hasattr(shift_date, "month") else "?"
            lines.append(f"• {d}.{m} — {fmt_hours(hours)}")
    else:
        lines.append("\nСмен в БД пока нет.")

    return "\n".join(lines)


async def _send_user_card(message: Message, user_id: int) -> None:
    text = await _format_user_card(user_id)
    await message.answer(text, reply_markup=user_card_kb(user_id))


async def _reconcile_track_hours_month(year: int, month: int) -> list[str]:
    mismatches: list[str] = []
    users = await list_track_hours_users()
    for user_id, name, role in users:
        try:
            shifts = await get_shifts_for_month(user_id, year, month)
        except Exception as e:
            mismatches.append(f"{name}: ошибка чтения смен — {e}")
            continue

        for shift_date, hours, *_rest in shifts:
            if not hours or float(hours) <= 0:
                continue
            day = shift_date.day if hasattr(shift_date, "day") else int(str(shift_date)[-2:])
            if not schedule.is_day_published(day, month, year):
                continue
            try:
                row, _ = await schedule.find_row(name, day, month, year, target_role=role)
                value = await schedule.get_day_value(row, day, month, year) if row else None
                sheet_work = is_work_shift(value)
            except Exception as e:
                mismatches.append(f"{name} {day}.{month}: не удалось прочитать таблицу — {e}")
                continue
            if not sheet_work:
                mismatches.append(
                    f"{name} {day}.{month}: в БД {fmt_hours(hours)}, в таблице выходной"
                )

        if len(mismatches) >= 20:
            break

    return mismatches


def _format_monitor_text(stats: dict) -> str:
    lines = [
        "👁 Мониторинг schedule_watch\n",
        f"Зарегистрировано: {stats['registered']}",
        f"Snapshots в БД: {stats['snapshots']}",
        f"Без snapshot: {stats['missing_snapshots']}",
        f"Окно отслеживания: {WATCH_DAYS} дн.",
        f"С учётом часов: {stats['track_hours']}",
    ]
    missing = stats.get("missing_users") or []
    if missing:
        lines.append("\nБез snapshot (не получат пуш об изменениях):")
        for user_id, name in missing:
            lines.append(f"• {name or '—'} (`{user_id}`)")
    else:
        lines.append("\nУ всех зарегистрированных есть snapshot.")
    lines.append("\nНажми ⚖️ Сверка — сверка часов в БД с Google Sheets.")
    return "\n".join(lines)


async def _send_health(message: Message) -> None:
    now = now_local()
    db_status = "unknown"
    notify_count = "?"
    notify_hours_count = "?"
    registered_users = "?"
    snapshots = "?"
    departments = get_departments_status()

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE notify=1")
        notify_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM users WHERE notify_hours=1")
        notify_hours_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM users WHERE name IS NOT NULL AND name != ''")
        registered_users = cursor.fetchone()[0]
        try:
            cursor.execute("SELECT COUNT(*) FROM schedule_snapshots")
            snapshots = cursor.fetchone()[0]
        except Exception:
            snapshots = "n/a"
        cursor.close()
        conn.close()
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"

    unique_gids = sorted({int(gid) for gid in SHEET_GID_MAP.values()})
    oldest_age = "?"
    if cached_time:
        try:
            oldest_age = f"{max(int((now - ts).total_seconds()) for ts in cached_time.values())} сек."
        except Exception:
            oldest_age = "?"

    sheets_probe = "не проверялся"
    if unique_gids:
        probe_gid = unique_gids[0]
        if probe_gid in cached_df:
            shape = getattr(cached_df[probe_gid], "shape", None)
            sheets_probe = f"gid={probe_gid} ok, shape={shape}"
        else:
            sheets_probe = f"gid={probe_gid} не в кэше"

    text = (
        "🛠 Статус\n\n"
        f"Время: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Таймзона: {APP_TIMEZONE_NAME}\n"
        f"БД: {db_status}\n"
        f"Пользователей с именем: {registered_users}\n"
        f"Уведомления смен: {notify_count} чел.\n"
        f"Уведомления часов: {notify_hours_count} чел.\n"
        f"Snapshots графика: {snapshots}\n"
        f"Отделов загружено: {departments.get('department_count', '?')}\n"
        f"Периодов в БД: {len(SHEET_GID_MAP)}\n"
        f"Уникальных gid: {len(unique_gids)}\n"
        f"Кэшированных gid: {len(cached_df)}\n"
        f"Самый старый кэш: {oldest_age}\n"
        f"Sheets: {sheets_probe}\n"
    )
    await message.answer(text, reply_markup=admin_main_kb())


async def _send_cache(message: Message) -> None:
    now = now_local()
    if not cached_df:
        return await message.answer("🧹 Кэш Google Sheets пуст.", reply_markup=admin_main_kb())

    lines = ["🧠 Кэш Google Sheets\n"]
    for gid, df in cached_df.items():
        ts = cached_time.get(gid)
        age = "?"
        if ts:
            try:
                age = f"{int((now - ts).total_seconds())} сек."
            except Exception:
                age = "?"
        shape = getattr(df, "shape", None)
        lines.append(f"gid={gid}: age={age}, shape={shape}")

    await message.answer("\n".join(lines), reply_markup=admin_main_kb())


async def _reload_periods(message: Message) -> None:
    try:
        count = await reload_from_db()
    except Exception as e:
        logging.exception("admin_reload_periods error: %s", e)
        return await message.answer(f"⚠️ Не удалось перезагрузить периоды: {e}")
    await record_action(message.from_user.id, "reload_periods", f"count={count}")
    await bump_sheet_cache_signal()
    await message.answer(
        f"✅ Периоды перезагружены из БД: {count}\n{_main_cache_pickup_hint()}",
        reply_markup=admin_main_kb(),
    )


async def _reload_sheets(message: Message) -> None:
    if _load_full_sheet is None:
        return await message.answer("⚠️ admin router не настроен.")

    clear_sheet_cache()
    try:
        await reload_from_db()
        loaded, failed, errors = await load_all_sheet_gids()
        await record_action(
            message.from_user.id,
            "reload_sheets",
            f"loaded={loaded}, failed={failed}",
        )
        await bump_sheet_cache_signal()
        lines = [
            f"✅ Периоды перезагружены, листов в кэше: {loaded}.",
            _main_cache_pickup_hint(),
        ]
        if failed:
            lines.append(f"⚠️ Не загрузилось: {failed}")
            lines.extend(errors[:3])
        await message.answer("\n".join(lines), reply_markup=admin_main_kb())
    except Exception as e:
        logging.exception("admin_reload_sheets error: %s", e)
        await message.answer(
            f"⚠️ Кэш сброшен, но загрузка таблиц завершилась ошибкой: {e}",
            reply_markup=admin_main_kb(),
        )


def _parse_month_button(text: str) -> tuple[int, int] | None:
    match = _MONTH_YEAR_RE.match(text.strip())
    if not match:
        return None
    month_name, year_str = match.group(1), match.group(2)
    for month in range(1, 13):
        if month_label(month) == month_name:
            return int(year_str), month
    return None


def _parse_stats_month(text: str) -> tuple[int, int] | None:
    cleaned = (text or "").replace("📈", "").strip()
    return _parse_month_button(cleaned)


def _format_logs_text(rows: list[tuple]) -> str:
    if not rows:
        return "📜 Логи пусты — действия админа будут записываться отсюда."

    lines = [f"📜 Логи (последние {len(rows)})\n"]
    for created_at, admin_id, action, details in rows:
        ts = created_at
        if hasattr(ts, "astimezone"):
            ts = ts.astimezone(now_local().tzinfo)
        time_label = ts.strftime("%d.%m %H:%M") if hasattr(ts, "strftime") else str(ts)
        label = _ACTION_LABELS.get(action, action)
        line = f"{time_label} | {label} | id {admin_id}"
        if details:
            line += f"\n  {details}"
        lines.append(line)
    text = "\n\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n…"
    return text


async def _send_shift_stats(message: Message, year: int, month: int) -> None:
    stats = await get_shift_stats(year, month)
    lines = [
        f"📈 Статистика смен — {month_label(month)} {year}\n",
        f"Всего смен: {stats['total_shifts']}",
        f"Сумма часов: {fmt_hours(stats['total_hours'])}",
        f"Сотрудников: {stats['people_count']}\n",
    ]
    if not stats["rows"]:
        lines.append("Нет внесённых смен за этот месяц.")
    else:
        for name, role, shift_count, hours in stats["rows"]:
            lines.append(
                f"• {name} ({role}): {shift_count} см., {fmt_hours(hours)} ч"
            )
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n…"
    await message.answer(text, reply_markup=admin_main_kb())


def _parse_half_button(text: str, year: int, month: int) -> int | None:
    if _HALF_FIRST_RE.match(text):
        return 1
    if _HALF_SECOND_RE.match(text):
        return 16
    return None


async def _save_period(
    message: Message,
    state: FSMContext,
    year: int,
    month: int,
    start_day: int,
    gid: str,
) -> None:
    try:
        count = await add_period(year, month, start_day, gid)
    except Exception as e:
        logging.exception("admin save period error: %s", e)
        await state.clear()
        return await message.answer(f"⚠️ Не удалось сохранить период: {e}", reply_markup=admin_main_kb())

    end_day = _period_end_day(year, month, start_day)
    await record_action(
        message.from_user.id,
        "save_period",
        f"{start_day}–{end_day} {month_label(month)} {year}, gid={gid}",
    )
    await bump_sheet_cache_signal()
    await state.clear()
    await message.answer(
        f"✅ Период {start_day}–{end_day} {month_label(month)} {year} сохранён.\n"
        f"gid={gid}\n"
        f"Всего периодов: {count}\n\n"
        f"{_main_cache_pickup_hint()}",
        reply_markup=admin_main_kb(),
    )


@router.message(F.text == "/start")
@router.message(F.text == BTN_HELP)
@router.message(F.text == "/help")
async def admin_start(message: Message, state: FSMContext):
    if _deny(message):
        return await message.answer("⛔ Нет доступа. Этот бот только для администраторов.")
    await state.clear()
    await message.answer(
        "🛠 Admin-бот расписания\n\n"
        "Используй кнопки ниже или команды:\n"
        "/periods /health /cache\n"
        "🔍 Пользователь — карточка, тест, snapshot\n"
        "👁 Мониторинг — schedule_watch\n"
        "⚖️ Сверка — часы в БД vs Google Sheets\n"
        "🔔 Проверка — алерты о проблемах системы\n"
        "📢 Рассылка — HTML и кнопка Mini App\n"
        "📈 Статистика — смены по месяцам\n"
        "💰 Ставки — ₽/час по ролям\n"
        "📜 Логи — последние действия админа",
        reply_markup=admin_main_kb(),
    )


@router.message(F.text == BTN_CANCEL)
async def admin_cancel(message: Message, state: FSMContext):
    if _deny(message):
        return
    await state.clear()
    await message.answer("Отменено.", reply_markup=admin_main_kb())


@router.message(F.text == BTN_STATUS)
@router.message(F.text == "/health")
async def admin_health(message: Message, state: FSMContext):
    if _deny(message):
        return
    await state.clear()
    await _send_health(message)


@router.message(F.text == BTN_CACHE)
@router.message(F.text == "/cache")
async def admin_cache(message: Message, state: FSMContext):
    if _deny(message):
        return
    await state.clear()
    await _send_cache(message)


@router.message(F.text == BTN_RATES)
async def admin_rates(message: Message, state: FSMContext):
    if _deny(message):
        return await message.answer("⛔ Нет доступа. Этот бот только для администраторов.")
    await state.clear()
    await reload_rates_from_db(quiet=True)
    await message.answer(
        format_rates_text(),
        reply_markup=rates_inline_kb(),
    )


@router.callback_query(F.data.startswith(f"{CB_EDIT_RATE}"))
async def admin_rate_edit_start(callback: CallbackQuery, state: FSMContext):
    if await _deny_callback(callback):
        return

    role_key = callback.data[len(CB_EDIT_RATE):]
    if not role_key:
        return await callback.answer("Некорректная роль", show_alert=True)

    await state.set_state(AdminRatesStates.waiting_value)
    await state.update_data(rate_role=role_key)
    await callback.answer()
    await callback.message.answer(
        f"Введи новую ставку ₽/час для {role_label(role_key)}.\n"
        "Только число, например: 350",
        reply_markup=admin_cancel_kb(),
    )


@router.message(AdminRatesStates.waiting_value)
async def admin_rate_save(message: Message, state: FSMContext):
    if _deny(message):
        return

    if message.text == BTN_CANCEL:
        await state.clear()
        return await message.answer("Отменено.", reply_markup=admin_main_kb())

    raw = (message.text or "").strip().replace(" ", "").replace("₽", "")
    if not raw.isdigit():
        return await message.answer(
            "⚠️ Введи целое число, например 350.",
            reply_markup=admin_cancel_kb(),
        )

    rate = int(raw)
    data = await state.get_data()
    role_key = data.get("rate_role")
    if not role_key:
        await state.clear()
        return await message.answer("⚠️ Роль не выбрана. Нажми 💰 Ставки снова.", reply_markup=admin_main_kb())

    try:
        await set_rate(role_key, rate)
    except Exception as e:
        logging.exception("admin set rate error: %s", e)
        return await message.answer(f"⚠️ Не удалось сохранить: {e}", reply_markup=admin_main_kb())

    await bump_rates_signal()
    await record_action(
        message.from_user.id,
        "update_rate",
        f"{role_key}={rate}",
    )
    await state.clear()
    await message.answer(
        f"✅ {role_label(role_key)}: {rate:,} ₽/час\n\nОсновной бот подхватит в течение ~3 мин.".replace(",", " "),
        reply_markup=admin_main_kb(),
    )
    await message.answer(format_rates_text(), reply_markup=rates_inline_kb())


@router.message(F.text == BTN_STATS)
async def admin_stats_start(message: Message, state: FSMContext):
    if _deny(message):
        return
    await state.set_state(AdminStatsStates.choosing_month)
    await message.answer(
        "Выбери месяц для статистики смен:",
        reply_markup=stats_month_kb(),
    )


@router.message(AdminStatsStates.choosing_month)
async def admin_stats_month(message: Message, state: FSMContext):
    if _deny(message):
        return
    if message.text == BTN_CANCEL:
        await state.clear()
        return await message.answer("Отменено.", reply_markup=admin_main_kb())

    parsed = _parse_stats_month(message.text or "")
    if not parsed:
        return await message.answer("Выбери месяц кнопкой ниже.", reply_markup=stats_month_kb())

    year, month = parsed
    await state.clear()
    await _send_shift_stats(message, year, month)


@router.message(F.text == BTN_LOGS)
async def admin_logs(message: Message, state: FSMContext):
    if _deny(message):
        return
    await state.clear()
    rows = await list_recent_logs()
    await message.answer(_format_logs_text(rows), reply_markup=admin_main_kb())


@router.message(F.text == BTN_RELOAD_PERIODS)
@router.message(F.text == "/reload_periods")
async def admin_reload_periods(message: Message, state: FSMContext):
    if _deny(message):
        return
    await state.clear()
    await _reload_periods(message)


@router.message(F.text == BTN_RELOAD_SHEETS)
@router.message(F.text == "/reload_sheets")
async def admin_reload_sheets(message: Message, state: FSMContext):
    if _deny(message):
        return
    await state.clear()
    await _reload_sheets(message)


@router.message(F.text == BTN_PERIODS)
@router.message(F.text == "/periods")
async def admin_periods(message: Message, state: FSMContext):
    if _deny(message):
        return
    await state.clear()
    keys = sorted(SHEET_GID_MAP.keys())
    await message.answer(
        _format_periods_text(),
        reply_markup=periods_inline_kb(keys) if keys else admin_main_kb(),
    )


@router.message(F.text == BTN_ADD_PERIOD)
async def admin_add_period_start(message: Message, state: FSMContext):
    if _deny(message):
        return
    await state.set_state(AdminAddPeriodStates.choosing_month)
    await message.answer(
        "Выбери месяц для нового периода:",
        reply_markup=add_period_month_kb(),
    )


@router.message(AdminAddPeriodStates.choosing_month)
async def admin_add_period_month(message: Message, state: FSMContext):
    if _deny(message):
        return
    if message.text == BTN_CANCEL:
        await state.clear()
        return await message.answer("Отменено.", reply_markup=admin_main_kb())

    parsed = _parse_month_button(message.text or "")
    if not parsed:
        return await message.answer("Выбери месяц кнопкой ниже.", reply_markup=add_period_month_kb())

    year, month = parsed
    await state.update_data(year=year, month=month)
    await state.set_state(AdminAddPeriodStates.choosing_half)
    await message.answer(
        f"Выбери половину месяца ({month_label(month)} {year}):",
        reply_markup=add_period_half_kb(year, month),
    )


@router.message(AdminAddPeriodStates.choosing_half)
async def admin_add_period_half(message: Message, state: FSMContext):
    if _deny(message):
        return
    if message.text == BTN_CANCEL:
        await state.clear()
        return await message.answer("Отменено.", reply_markup=admin_main_kb())

    data = await state.get_data()
    year, month = data["year"], data["month"]
    start_day = _parse_half_button(message.text or "", year, month)
    if start_day is None:
        return await message.answer(
            "Выбери период кнопкой ниже.",
            reply_markup=add_period_half_kb(year, month),
        )

    existing = SHEET_GID_MAP.get((year, month, start_day))
    await state.update_data(start_day=start_day)
    await state.set_state(AdminAddPeriodStates.waiting_gid)

    end_day = _period_end_day(year, month, start_day)
    hint = ""
    if existing:
        hint = f"\n\n⚠️ Период уже есть (gid={existing}) — новый gid заменит старый."
    await message.answer(
        f"Введи gid Google Sheets для {start_day}–{end_day} {month_label(month)} {year}:{hint}",
        reply_markup=admin_cancel_kb(),
    )


@router.message(AdminAddPeriodStates.waiting_gid)
async def admin_add_period_gid(message: Message, state: FSMContext):
    if _deny(message):
        return
    if message.text == BTN_CANCEL:
        await state.clear()
        return await message.answer("Отменено.", reply_markup=admin_main_kb())

    gid = (message.text or "").strip()
    if not gid.isdigit():
        return await message.answer("⚠️ gid должен содержать только цифры.", reply_markup=admin_cancel_kb())

    data = await state.get_data()
    await _save_period(message, state, data["year"], data["month"], data["start_day"], gid)


@router.message(F.text.regexp(r"^/add_period(\s|$)"))
async def admin_add_period_command(message: Message, state: FSMContext):
    if _deny(message):
        return
    await state.clear()

    parts = (message.text or "").split()
    if len(parts) != 5:
        return await message.answer(
            "Формат: /add_period год месяц start_day gid\n"
            "Или нажми «➕ Добавить период».",
            reply_markup=admin_main_kb(),
        )

    try:
        year = int(parts[1])
        month = int(parts[2])
        start_day = int(parts[3])
        gid = parts[4].strip()
    except ValueError:
        return await message.answer("⚠️ год, месяц и start_day должны быть числами.")

    if not (1 <= month <= 12):
        return await message.answer("⚠️ месяц должен быть от 1 до 12.")
    if start_day not in (1, 16):
        return await message.answer("⚠️ start_day только 1 или 16.")
    if not gid.isdigit():
        return await message.answer("⚠️ gid должен содержать только цифры.")

    await _save_period(message, state, year, month, start_day, gid)


@router.message(F.text == BTN_DASHBOARD)
async def admin_dashboard(message: Message, state: FSMContext):
    if _deny(message):
        return
    await state.clear()
    stats = await get_dashboard_stats()
    text = (
        "📊 Дашборд\n\n"
        f"👤 Пользователей: {stats['users_total']} "
        f"(с именем: {stats['users_named']})\n"
        f"🔔 Уведомления смен: {stats['notify_shift']}\n"
        f"⏱ Уведомления часов: {stats['notify_hours']}\n"
        f"📝 Учёт часов вкл: {stats['track_hours']}\n"
        f"📋 Смен в БД: {stats['shifts_total']} "
        f"(за {month_label(stats['month'])}: {stats['shifts_month']})\n"
        f"📅 Периодов в кэше: {len(SHEET_GID_MAP)}\n"
        f"🧠 Кэш листов: {len(cached_df)} gid"
    )
    await message.answer(text, reply_markup=admin_main_kb())


@router.message(F.text == BTN_USERS)
async def admin_users(message: Message, state: FSMContext):
    if _deny(message):
        return
    await state.clear()
    users = await list_users()
    if not users:
        return await message.answer("👥 Пользователей нет.", reply_markup=admin_main_kb())

    lines = [f"👥 Пользователи ({len(users)})\n"]
    for row in users:
        user_id, name, role, notify, notify_time, notify_hours, track_hours = row
        display_name = name or "—"
        role_text = role or "—"
        flags = []
        if notify:
            flags.append(f"🔔 {notify_time or '?'}")
        if notify_hours:
            flags.append("⏱ увед.")
        if track_hours:
            flags.append("📝 часы")
        flag_text = ", ".join(flags) if flags else "без уведомлений"
        lines.append(f"• {display_name} (`{user_id}`) — {role_text} | {flag_text}")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n…"
    await message.answer(text, reply_markup=admin_main_kb())


@router.message(F.text == BTN_USER_LOOKUP)
async def admin_user_lookup_start(message: Message, state: FSMContext):
    if _deny(message):
        return
    await state.set_state(AdminUserLookupStates.waiting_query)
    await message.answer(
        "🔍 Введи имя или `user_id` пользователя:",
        reply_markup=admin_cancel_kb(),
    )


@router.message(AdminUserLookupStates.waiting_query)
async def admin_user_lookup_query(message: Message, state: FSMContext):
    if _deny(message):
        return
    if message.text == BTN_CANCEL:
        await state.clear()
        return await message.answer("Отменено.", reply_markup=admin_main_kb())

    query = (message.text or "").strip()
    if not query:
        return await message.answer("Введи имя или id.", reply_markup=admin_cancel_kb())

    matches = await search_users(query)
    await state.clear()
    if not matches:
        return await message.answer(
            f"Никого не нашёл по запросу «{query}».",
            reply_markup=admin_main_kb(),
        )
    if len(matches) == 1:
        return await _send_user_card(message, matches[0][0])

    lines = [f"Найдено {len(matches)}. Выбери пользователя:"]
    for user_id, name, role, *_rest in matches:
        lines.append(f"• {name or '—'} (`{user_id}`) — {role or '—'}")
    await message.answer(
        "\n".join(lines),
        reply_markup=user_pick_kb(matches),
    )


async def _run_reconcile(message: Message, admin_id: int) -> None:
    today = now_local().date()
    await message.answer("⏳ Сверяю часы с таблицей...")
    mismatches = await _reconcile_track_hours_month(today.year, today.month)
    await record_action(
        admin_id,
        "reconcile_shifts",
        f"{today.year}-{today.month}, mismatches={len(mismatches)}",
    )
    if not mismatches:
        text = (
            f"⚖️ Сверка Sheets ↔ БД за {month_label(today.month)} {today.year}\n\n"
            "Расхождений не найдено (смены в БД совпадают с таблицей)."
        )
    else:
        lines = [
            f"⚖️ Сверка Sheets ↔ БД за {month_label(today.month)} {today.year}\n",
            f"Найдено расхождений: {len(mismatches)}\n",
        ]
        lines.extend(mismatches[:15])
        if len(mismatches) > 15:
            lines.append(f"\n…и ещё {len(mismatches) - 15}")
        text = "\n".join(lines)
    await message.answer(text, reply_markup=admin_main_kb())


@router.message(F.text == BTN_RECONCILE)
async def admin_reconcile_button(message: Message, state: FSMContext):
    if _deny(message):
        return
    await state.clear()
    await _run_reconcile(message, message.from_user.id)


@router.message(F.text == BTN_MONITOR)
async def admin_monitor(message: Message, state: FSMContext):
    if _deny(message):
        return
    await state.clear()
    stats = await get_watch_monitor_stats()
    await message.answer(_format_monitor_text(stats), reply_markup=monitor_kb())


@router.callback_query(F.data.startswith(CB_USER_OPEN))
async def admin_user_open(callback: CallbackQuery, state: FSMContext):
    if await _deny_callback(callback):
        return
    await state.clear()
    user_id = int(callback.data[len(CB_USER_OPEN):])
    await callback.answer()
    await _send_user_card(callback.message, user_id)


@router.callback_query(F.data.startswith(CB_USER_TEST))
async def admin_user_test_notify(callback: CallbackQuery, state: FSMContext):
    if await _deny_callback(callback):
        return
    user_id = int(callback.data[len(CB_USER_TEST):])
    if not BOT_TOKEN:
        return await callback.answer("BOT_TOKEN не настроен", show_alert=True)

    user = await get_user(user_id)
    name = user[1] if user else None
    ok = await send_user_message(
        user_id,
        "🧪 Тестовое уведомление от admin-бота.\nЕсли видишь это — доставка работает.",
    )
    await record_action(
        callback.from_user.id,
        "user_test_notify",
        f"user_id={user_id}, name={name}, ok={ok}",
    )
    await callback.answer("Отправлено" if ok else "Ошибка доставки", show_alert=not ok)
    if not ok:
        await callback.message.answer(
            f"⚠️ Не удалось отправить тест пользователю `{user_id}`.",
            reply_markup=user_card_kb(user_id),
        )


@router.callback_query(F.data.startswith(CB_USER_RESET_SNAP))
async def admin_user_reset_snapshot(callback: CallbackQuery, state: FSMContext):
    if await _deny_callback(callback):
        return
    user_id = int(callback.data[len(CB_USER_RESET_SNAP):])
    user = await get_user(user_id)
    name = user[1] if user else None
    await reset_user_snapshot(user_id)
    await record_action(
        callback.from_user.id,
        "user_reset_snapshot",
        f"user_id={user_id}, name={name}",
    )
    await callback.answer("Snapshot сброшен")
    await callback.message.answer(
        f"✅ Snapshot сброшен для {name or user_id}.\n"
        "При следующей проверке графика baseline пересоздастся.",
        reply_markup=user_card_kb(user_id),
    )


@router.callback_query(F.data.startswith(CB_USER_CHECK))
async def admin_user_check_schedule(callback: CallbackQuery, state: FSMContext):
    if await _deny_callback(callback):
        return
    user_id = int(callback.data[len(CB_USER_CHECK):])
    user = await get_user(user_id)
    if not user or not user[1]:
        return await callback.answer("У пользователя нет имени", show_alert=True)

    name, role = user[1], user[4]
    await callback.answer("Проверяю...")
    try:
        await check_user_schedule(user_id, name, role)
    except Exception as e:
        logging.exception("admin_user_check_schedule: %s", e)
        return await callback.message.answer(
            f"⚠️ Ошибка проверки графика: {e}",
            reply_markup=user_card_kb(user_id),
        )

    await record_action(
        callback.from_user.id,
        "user_check_schedule",
        f"user_id={user_id}, name={name}",
    )
    await callback.message.answer(
        f"✅ Проверка графика для {name} завершена.\n"
        "Если были изменения — пользователь получит уведомление в основном боте.",
        reply_markup=user_card_kb(user_id),
    )


@router.callback_query(F.data == CB_RECONCILE)
async def admin_reconcile_shifts(callback: CallbackQuery, state: FSMContext):
    if await _deny_callback(callback):
        return
    await callback.answer()
    await _run_reconcile(callback.message, callback.from_user.id)


@router.message(F.text == BTN_ALERTS)
async def admin_health_check(message: Message, state: FSMContext):
    if _deny(message):
        return
    await state.clear()
    result = await run_health_alerts()
    extra = ""
    if result["sent_new"]:
        extra = f"\n\nОтправлено новых алертов: {result['sent_new']}"
    if result["sent_resolved"]:
        extra += f"\nВосстановлено: {result['sent_resolved']}"
    await record_action(
        message.from_user.id,
        "health_check",
        f"issues={result['active_count']}, sent={result['sent_new']}",
    )
    await message.answer(result["report"] + extra, reply_markup=admin_main_kb())


def _broadcast_parse_mode(fmt: str) -> str | None:
    if fmt in (BC_FMT_HTML, BC_FMT_HTML_MINIAPP):
        return "HTML"
    return None


def _broadcast_reply_markup(fmt: str) -> dict | None:
    if fmt == BC_FMT_HTML_MINIAPP:
        return miniapp_broadcast_markup()
    return None


def _broadcast_format_hint(fmt: str) -> str:
    if fmt == BC_FMT_HTML:
        return "\n\nФормат: HTML (<b>жирный</b>, <i>курсив</i>, <code>код</code>)."
    if fmt == BC_FMT_HTML_MINIAPP:
        hint = "\n\nФормат: HTML + кнопка «Открыть TNG Alice»."
        if not MINIAPP_URL:
            hint += "\n⚠️ MINIAPP_URL не задан — кнопка не добавится."
        return hint
    return ""


@router.message(F.text == BTN_BROADCAST)
async def admin_broadcast_start(message: Message, state: FSMContext):
    if _deny(message):
        return
    await state.set_state(AdminBroadcastStates.choosing_audience)
    await message.answer(
        "📢 Кому отправить рассылку?",
        reply_markup=broadcast_audience_kb(),
    )


@router.callback_query(F.data.startswith(CB_BC_AUDIENCE))
async def admin_broadcast_audience(callback: CallbackQuery, state: FSMContext):
    if await _deny_callback(callback):
        return

    audience = callback.data[len(CB_BC_AUDIENCE):]
    if audience not in BC_AUDIENCE_LABELS:
        return await callback.answer("Неизвестная аудитория", show_alert=True)

    recipients = await get_broadcast_recipients(audience)
    await state.update_data(broadcast_audience=audience)
    await state.set_state(AdminBroadcastStates.choosing_format)
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        f"Аудитория: <b>{BC_AUDIENCE_LABELS[audience]}</b> — {len(recipients)} чел.\n\n"
        "Выбери формат сообщения:",
        parse_mode="HTML",
        reply_markup=broadcast_format_kb(),
    )


@router.callback_query(F.data.startswith(CB_BC_FORMAT))
async def admin_broadcast_format(callback: CallbackQuery, state: FSMContext):
    if await _deny_callback(callback):
        return

    fmt = callback.data[len(CB_BC_FORMAT):]
    if fmt not in BC_FMT_LABELS:
        return await callback.answer("Неизвестный формат", show_alert=True)

    data = await state.get_data()
    audience = data.get("broadcast_audience", "notify")
    recipients = await get_broadcast_recipients(audience)
    await state.update_data(broadcast_format=fmt)
    await state.set_state(AdminBroadcastStates.waiting_text)
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        f"Аудитория: {BC_AUDIENCE_LABELS.get(audience, audience)} — {len(recipients)} чел.\n"
        f"Формат: {BC_FMT_LABELS[fmt]}"
        f"{_broadcast_format_hint(fmt)}\n\n"
        "Отправь текст сообщения одним сообщением:",
        reply_markup=admin_cancel_kb(),
    )


@router.message(AdminBroadcastStates.waiting_text)
async def admin_broadcast_preview(message: Message, state: FSMContext):
    if _deny(message):
        return
    if message.text == BTN_CANCEL:
        await state.clear()
        return await message.answer("Отменено.", reply_markup=admin_main_kb())

    text = (message.text or "").strip()
    if not text:
        return await message.answer("Текст не может быть пустым.", reply_markup=admin_cancel_kb())

    data = await state.get_data()
    audience = data.get("broadcast_audience", "notify")
    fmt = data.get("broadcast_format", BC_FMT_PLAIN)
    recipients = await get_broadcast_recipients(audience)
    await state.update_data(broadcast_text=text)
    aud_label = BC_AUDIENCE_LABELS.get(audience, audience)
    fmt_label = BC_FMT_LABELS.get(fmt, fmt)
    preview = (
        f"Аудитория: {aud_label}\n"
        f"Формат: {fmt_label}\n"
        f"Получателей: {len(recipients)}\n\n"
        f"Текст:\n{text}\n\n"
        "Отправить?"
    )
    parse_mode = _broadcast_parse_mode(fmt)
    await message.answer(
        preview,
        parse_mode=parse_mode,
        reply_markup=broadcast_confirm_kb(),
    )


@router.callback_query(F.data == CB_BROADCAST_CONFIRM)
async def admin_broadcast_send(callback: CallbackQuery, state: FSMContext):
    if await _deny_callback(callback):
        return

    data = await state.get_data()
    text = data.get("broadcast_text")
    if not text:
        await state.clear()
        return await callback.answer("Нет текста", show_alert=True)

    audience = data.get("broadcast_audience", "notify")
    fmt = data.get("broadcast_format", BC_FMT_PLAIN)
    recipients = await get_broadcast_recipients(audience)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)

    if not BOT_TOKEN:
        await state.clear()
        return await callback.message.answer(
            "⚠️ У основного бота не настроен `BOT_TOKEN`, рассылка недоступна.",
            reply_markup=admin_main_kb(),
        )

    parse_mode = _broadcast_parse_mode(fmt)
    reply_markup = _broadcast_reply_markup(fmt)

    sent, failed = 0, 0
    failed_names: list[str] = []
    for user_id, name in recipients:
        try:
            ok = await send_user_message(
                user_id,
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            if ok:
                sent += 1
            else:
                failed += 1
                failed_names.append(name or str(user_id))
                logging.warning("broadcast failed user_id=%s name=%s", user_id, name)
        except Exception as e:
            logging.warning("broadcast failed user_id=%s name=%s: %s", user_id, name, e)
            failed += 1
            failed_names.append(name or str(user_id))
        await asyncio.sleep(0.05)

    await state.clear()
    await record_action(
        callback.from_user.id,
        "broadcast",
        f"audience={audience}, fmt={fmt}, sent={sent}, failed={failed}, len={len(text)}",
    )
    failed_hint = ""
    if failed_names:
        preview = ", ".join(failed_names[:6])
        extra = "" if len(failed_names) <= 6 else f" и ещё {len(failed_names) - 6}"
        failed_hint = f"\nНе дошло: {preview}{extra}"
    await callback.message.answer(
        f"✅ Рассылка завершена.\nОтправлено: {sent}\nОшибок: {failed}{failed_hint}",
        reply_markup=admin_main_kb(),
    )


@router.callback_query(F.data == CB_CANCEL)
async def admin_inline_cancel(callback: CallbackQuery, state: FSMContext):
    if await _deny_callback(callback):
        return
    await state.clear()
    await callback.answer("Отменено")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer("Отменено.", reply_markup=admin_main_kb())


@router.callback_query(F.data.startswith(f"{CB_DELETE_PERIOD}:"))
async def admin_delete_period_ask(callback: CallbackQuery, state: FSMContext):
    if await _deny_callback(callback):
        return

    parts = callback.data.split(":")
    if len(parts) != 4:
        return await callback.answer("Некорректные данные", show_alert=True)

    year, month, start_day = int(parts[1]), int(parts[2]), int(parts[3])
    end_day = _period_end_day(year, month, start_day)
    gid = SHEET_GID_MAP.get((year, month, start_day), "?")

    await callback.answer()
    await callback.message.answer(
        f"🗑 Удалить период {start_day}–{end_day} {month_label(month)} {year}?\n"
        f"gid={gid}\n\n"
        "Prod и test перестанут видеть этот период после синхронизации.",
        reply_markup=confirm_delete_kb(year, month, start_day),
    )


@router.callback_query(F.data.startswith(f"{CB_CONFIRM_DELETE}:"))
async def admin_delete_period_confirm(callback: CallbackQuery, state: FSMContext):
    if await _deny_callback(callback):
        return

    parts = callback.data.split(":")
    if len(parts) != 4:
        return await callback.answer("Некорректные данные", show_alert=True)

    year, month, start_day = int(parts[1]), int(parts[2]), int(parts[3])
    try:
        count = await remove_period(year, month, start_day)
    except Exception as e:
        logging.exception("delete period error: %s", e)
        return await callback.answer(f"Ошибка: {e}", show_alert=True)

    end_day = _period_end_day(year, month, start_day)
    await record_action(
        callback.from_user.id,
        "delete_period",
        f"{start_day}–{end_day} {month_label(month)} {year}",
    )
    await bump_sheet_cache_signal()
    await callback.answer("Удалено")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        f"✅ Период {start_day}–{end_day} {month_label(month)} {year} удалён.\n"
        f"Осталось периодов: {count}",
        reply_markup=admin_main_kb(),
    )


@router.callback_query(F.data.startswith(f"{CB_EDIT_PERIOD}:"))
async def admin_edit_period_start(callback: CallbackQuery, state: FSMContext):
    if await _deny_callback(callback):
        return

    parts = callback.data.split(":")
    if len(parts) != 4:
        return await callback.answer("Некорректные данные", show_alert=True)

    year, month, start_day = int(parts[1]), int(parts[2]), int(parts[3])
    gid = SHEET_GID_MAP.get((year, month, start_day), "?")
    end_day = _period_end_day(year, month, start_day)

    await state.set_state(AdminEditPeriodStates.waiting_gid)
    await state.update_data(year=year, month=month, start_day=start_day)
    await callback.answer()
    await callback.message.answer(
        f"✏️ Редактирование: {start_day}–{end_day} {month_label(month)} {year}\n"
        f"Текущий gid: {gid}\n\n"
        "Отправь новый gid (только цифры):",
        reply_markup=admin_cancel_kb(),
    )


@router.message(AdminEditPeriodStates.waiting_gid)
async def admin_edit_period_gid(message: Message, state: FSMContext):
    if _deny(message):
        return
    if message.text == BTN_CANCEL:
        await state.clear()
        return await message.answer("Отменено.", reply_markup=admin_main_kb())

    gid = (message.text or "").strip()
    if not gid.isdigit():
        return await message.answer("⚠️ gid должен содержать только цифры.", reply_markup=admin_cancel_kb())

    data = await state.get_data()
    await _save_period(message, state, data["year"], data["month"], data["start_day"], gid)


@router.callback_query(F.data == CB_RELOAD_SHEETS)
async def admin_reload_sheets_callback(callback: CallbackQuery, state: FSMContext):
    if await _deny_callback(callback):
        return
    await state.clear()
    await callback.answer()
    await _reload_sheets(callback.message)


@router.callback_query(F.data == CB_RELOAD_PERIODS)
async def admin_reload_periods_callback(callback: CallbackQuery, state: FSMContext):
    if await _deny_callback(callback):
        return
    await state.clear()
    await callback.answer()
    await _reload_periods(callback.message)
