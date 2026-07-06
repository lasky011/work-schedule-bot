"""Клавиатуры admin-бота."""

import calendar

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app_config import now_local
from ui_utils import month_label

BTN_RATES = "💰 Ставки"
BTN_STATS = "📈 Статистика"
BTN_LOGS = "📜 Логи"
BTN_DASHBOARD = "📊 Дашборд"
BTN_USERS = "👥 Пользователи"
BTN_USER_LOOKUP = "🔍 Пользователь"
BTN_MONITOR = "👁 Мониторинг"
BTN_RECONCILE = "⚖️ Сверка"
BTN_ALERTS = "🔔 Проверка"
BTN_BROADCAST = "📢 Рассылка"
BTN_PERIODS = "📅 Периоды"
BTN_ADD_PERIOD = "➕ Добавить период"
BTN_RELOAD_SHEETS = "🔄 Листы"
BTN_RELOAD_PERIODS = "🔄 Периоды"
BTN_STATUS = "🛠 Статус"
BTN_CACHE = "🧠 Кэш"
BTN_HELP = "📋 Справка"
BTN_CANCEL = "❌ Отмена"

CB_EDIT_PERIOD = "edit_period"
CB_DELETE_PERIOD = "del_period"
CB_CONFIRM_DELETE = "cfm_del"
CB_BROADCAST_CONFIRM = "bc_ok"
CB_BROADCAST_CANCEL = "bc_no"
CB_CANCEL = "adm_cancel"
CB_RELOAD_SHEETS = "reload_sheets"
CB_RELOAD_PERIODS = "reload_periods"
CB_BC_AUDIENCE = "bc_aud:"
CB_BC_FORMAT = "bc_fmt:"
CB_USER_OPEN = "usr:open:"
CB_USER_TEST = "usr:test:"
CB_USER_RESET_SNAP = "usr:snap:"
CB_USER_CHECK = "usr:chk:"
CB_RECONCILE = "adm:reconcile"
CB_EDIT_RATE = "rate:edit:"

BC_AUD_ALL = "all"
BC_AUD_NOTIFY = "notify"
BC_AUD_TRACK = "track"
BC_AUD_HOURS = "hours"

BC_FMT_PLAIN = "plain"
BC_FMT_HTML = "html"
BC_FMT_HTML_MINIAPP = "html_miniapp"

BC_FMT_LABELS = {
    BC_FMT_PLAIN: "📝 Обычный текст",
    BC_FMT_HTML: "🔤 HTML",
    BC_FMT_HTML_MINIAPP: "✨ HTML + Mini App",
}

BC_AUDIENCE_LABELS = {
    BC_AUD_ALL: "👥 Все сотрудники",
    BC_AUD_NOTIFY: "🔔 С уведомлениями смен",
    BC_AUD_TRACK: "⏱ С учётом часов",
    BC_AUD_HOURS: "⏱ Напоминания о часах",
}


def admin_main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_PERIODS), KeyboardButton(text=BTN_ADD_PERIOD)],
            [KeyboardButton(text=BTN_DASHBOARD), KeyboardButton(text=BTN_USERS)],
            [KeyboardButton(text=BTN_USER_LOOKUP), KeyboardButton(text=BTN_MONITOR)],
            [KeyboardButton(text=BTN_RECONCILE), KeyboardButton(text=BTN_ALERTS)],
            [KeyboardButton(text=BTN_STATS), KeyboardButton(text=BTN_LOGS)],
            [KeyboardButton(text=BTN_RATES), KeyboardButton(text=BTN_BROADCAST)],
            [KeyboardButton(text=BTN_RELOAD_SHEETS), KeyboardButton(text=BTN_RELOAD_PERIODS)],
            [KeyboardButton(text=BTN_STATUS), KeyboardButton(text=BTN_CACHE)],
            [KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
    )


def admin_cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
        resize_keyboard=True,
    )


def upcoming_month_choices(months_ahead: int = 4) -> list[tuple[int, int]]:
    now = now_local()
    year, month = now.year, now.month
    result: list[tuple[int, int]] = []
    for offset in range(months_ahead):
        total = (month - 1) + offset
        result.append((year + total // 12, (total % 12) + 1))
    return result


def add_period_month_kb() -> ReplyKeyboardMarkup:
    rows = []
    row: list[KeyboardButton] = []
    for year, month in upcoming_month_choices():
        row.append(KeyboardButton(text=f"{month_label(month)} {year}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([KeyboardButton(text=BTN_CANCEL)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def add_period_half_kb(year: int, month: int) -> ReplyKeyboardMarkup:
    last_day = calendar.monthrange(year, month)[1]
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=f"1–15 {month_label(month)}")],
            [KeyboardButton(text=f"16–{last_day} {month_label(month)}")],
            [KeyboardButton(text=BTN_CANCEL)],
        ],
        resize_keyboard=True,
    )


def periods_inline_kb(period_keys: list[tuple[int, int, int]]) -> InlineKeyboardMarkup:
    rows = []
    for year, month, start_day in period_keys:
        if start_day == 1:
            end_day = 15
        else:
            end_day = calendar.monthrange(year, month)[1]
        label = f"{start_day}–{end_day} {month_label(month)} {year}"
        rows.append([
            InlineKeyboardButton(
                text=f"✏️ {label}",
                callback_data=f"{CB_EDIT_PERIOD}:{year}:{month}:{start_day}",
            ),
            InlineKeyboardButton(
                text="🗑",
                callback_data=f"{CB_DELETE_PERIOD}:{year}:{month}:{start_day}",
            ),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_delete_kb(year: int, month: int, start_day: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Удалить",
                    callback_data=f"{CB_CONFIRM_DELETE}:{year}:{month}:{start_day}",
                ),
                InlineKeyboardButton(text="❌ Отмена", callback_data=CB_CANCEL),
            ],
        ]
    )


def broadcast_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data=CB_BROADCAST_CONFIRM),
                InlineKeyboardButton(text="❌ Отмена", callback_data=CB_CANCEL),
            ],
        ]
    )


def broadcast_audience_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=BC_AUDIENCE_LABELS[BC_AUD_NOTIFY], callback_data=f"{CB_BC_AUDIENCE}{BC_AUD_NOTIFY}")],
            [InlineKeyboardButton(text=BC_AUDIENCE_LABELS[BC_AUD_ALL], callback_data=f"{CB_BC_AUDIENCE}{BC_AUD_ALL}")],
            [
                InlineKeyboardButton(text=BC_AUDIENCE_LABELS[BC_AUD_TRACK], callback_data=f"{CB_BC_AUDIENCE}{BC_AUD_TRACK}"),
                InlineKeyboardButton(text=BC_AUDIENCE_LABELS[BC_AUD_HOURS], callback_data=f"{CB_BC_AUDIENCE}{BC_AUD_HOURS}"),
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=CB_CANCEL)],
        ]
    )


def stats_month_kb() -> ReplyKeyboardMarkup:
    rows = []
    row: list[KeyboardButton] = []
    for year, month in recent_month_choices():
        row.append(KeyboardButton(text=f"📈 {month_label(month)} {year}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([KeyboardButton(text=BTN_CANCEL)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def recent_month_choices(count: int = 6) -> list[tuple[int, int]]:
    now = now_local()
    year, month = now.year, now.month
    result: list[tuple[int, int]] = []
    for offset in range(count):
        mm = month - offset
        yy = year
        while mm <= 0:
            mm += 12
            yy -= 1
        result.append((yy, mm))
    result.reverse()
    return result


def broadcast_format_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=BC_FMT_LABELS[BC_FMT_PLAIN], callback_data=f"{CB_BC_FORMAT}{BC_FMT_PLAIN}")],
            [InlineKeyboardButton(text=BC_FMT_LABELS[BC_FMT_HTML], callback_data=f"{CB_BC_FORMAT}{BC_FMT_HTML}")],
            [InlineKeyboardButton(text=BC_FMT_LABELS[BC_FMT_HTML_MINIAPP], callback_data=f"{CB_BC_FORMAT}{BC_FMT_HTML_MINIAPP}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=CB_CANCEL)],
        ]
    )


def reload_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Листы", callback_data=CB_RELOAD_SHEETS),
                InlineKeyboardButton(text="🔄 Периоды из БД", callback_data=CB_RELOAD_PERIODS),
            ],
        ]
    )


def user_card_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📨 Тест", callback_data=f"{CB_USER_TEST}{user_id}"),
                InlineKeyboardButton(text="🔄 Snapshot", callback_data=f"{CB_USER_RESET_SNAP}{user_id}"),
            ],
            [
                InlineKeyboardButton(text="👁 Проверить график", callback_data=f"{CB_USER_CHECK}{user_id}"),
            ],
        ]
    )


def user_pick_kb(matches: list[tuple]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{name or '—'} ({user_id})",
                callback_data=f"{CB_USER_OPEN}{user_id}",
            )
        ]
        for user_id, name, *_ in matches
    ]
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data=CB_CANCEL)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def monitor_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚖️ Сверка", callback_data=CB_RECONCILE)],
        ]
    )


def rates_inline_kb() -> InlineKeyboardMarkup:
    from services.rates_service import ROLE_CATALOG

    rows = [
        [
            InlineKeyboardButton(
                text=f"✏️ {label}",
                callback_data=f"{CB_EDIT_RATE}{role_key}",
            )
        ]
        for role_key, label in ROLE_CATALOG
    ]
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data=CB_CANCEL)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
