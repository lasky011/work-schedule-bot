import asyncio
import functools
import os
import re
import calendar
import logging
import traceback
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, CallbackQuery
from aiogram_calendar import SimpleCalendar, SimpleCalendarCallback


from app_config import (
    BOT_TOKEN,
    DATABASE_URL,
    SHEET_ID,
    APP_TIMEZONE_NAME,
    APP_TIMEZONE,
    ADMIN_IDS,
    now_local,
    is_admin,
    validate_required_env,
)

validate_required_env()

from constants import (
    RATES,
    SHIFT_HOURS,
    SHIFT_END_NOTIFY,
    SHEET_GID_MAP,
)

from keyboards import (
    configure_keyboard_context,
    get_available_periods,
    _month_label_for_period,
    compare_period_kb,
    compare_kb,
    week_kb,
)

from sheets_client import (
    cached_df,
    cached_time,
    cache_locks,
    clear_sheet_cache,
    download_sheet,
)

from schedule_utils import (
    configure_schedule_utils,
    clean_value,
    detect_shift_type,
    is_work_shift,
    detect_shift,
    get_day_type,
    get_standard_hours,
    format_date,
    current_period,
)

from db import (
    USE_POSTGRES,
    init_pg_pool,
    get_db_connection,
    db_placeholder,
)

from repositories.users_repo import (
    save_user,
    get_user,
    get_user_name,
    get_notify_users,
)

from repositories.shifts_repo import (
    save_shift,
    get_shifts_for_month,
    delete_shift,
    get_shift_for_date,
)





def _clean_person_name_value(name) -> str:
    """
    Низкоуровневая очистка имени из Google Sheets.

    Пример:
    "Егор Капустин C 16:00" -> "Егор Капустин"
    """
    if name is None:
        return ""

    text = str(name).replace("\xa0", " ").strip()
    text = re.sub(r"\s+", " ", text)

    # Убираем хвосты вида "с 16:00", "С 16:00", "C 16:00".
    # Латинская C тоже учитывается.
    text = re.sub(r"\s+[сcСC]\s*\d{1,2}[:.]\d{2}\s*$", "", text).strip()

    return text


def clean_person_name(name: str) -> str:
    """
    Чистит имя сотрудника от служебных пометок в таблице.
    """
    return _clean_person_name_value(name)





def get_gid_for_day(day):
    now = now_local()
    return get_gid_for_day_month(day, now.month, now.year)

def get_gid_for_day_month(day, month, year):
    period_start = 1 if day <= 15 else 16
    return SHEET_GID_MAP.get((year, month, period_start))

dp = Dispatcher()




def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # ── users ──────────────────────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id     BIGINT PRIMARY KEY,
        name        TEXT,
        notify      INTEGER DEFAULT 0,
        notify_time TEXT,
        role        TEXT,
        track_hours INTEGER DEFAULT 0,
        notify_hours INTEGER DEFAULT 0,
        notify_hours_time TEXT
    )
    """)

    # Добавляем колонки если таблица существует со старой схемой
    extra_user_cols = [
        ("role",               "TEXT"),
        ("track_hours",        "INTEGER DEFAULT 0"),
        ("notify_hours",       "INTEGER DEFAULT 0"),
        ("notify_hours_time",  "TEXT"),
    ]
    for col, col_type in extra_user_cols:
        try:
            if USE_POSTGRES:
                cursor.execute(
                    f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {col_type}"
                )
            else:
                # SQLite не поддерживает IF NOT EXISTS в ALTER TABLE
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
        except Exception:
            pass  # колонка уже есть

    # ── shifts ─────────────────────────────────────────────────────────
    if USE_POSTGRES:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS shifts (
            id          SERIAL PRIMARY KEY,
            user_id     BIGINT NOT NULL,
            date        DATE NOT NULL,
            hours       NUMERIC(5,2) NOT NULL,
            shift_type  TEXT,
            is_standard BOOLEAN DEFAULT TRUE,
            note        TEXT,
            created_at  TIMESTAMP DEFAULT NOW(),
            UNIQUE (user_id, date)
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS shifts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            date        TEXT NOT NULL,
            hours       REAL NOT NULL,
            shift_type  TEXT,
            is_standard INTEGER DEFAULT 1,
            note        TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
            UNIQUE (user_id, date)
        )
        """)

    conn.commit()
    cursor.close()
    conn.close()


init_db()


async def load_sheet(day, month=None, year=None):
    global cached_df, cached_time
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year

    gid = get_gid_for_day_month(day, month, year)
    if gid is None:
        raise ValueError(f"Нет GID для {year}-{month}, день {day}. Добавь в SHEET_GID_MAP.")

    # Lock per GID: запросы разных листов идут параллельно
    if gid not in cache_locks:
        cache_locks[gid] = asyncio.Lock()

    async with cache_locks[gid]:
        now_time = now_local()
        if gid in cached_df and gid in cached_time:
            if (now_time - cached_time[gid]).total_seconds() < 60:
                return cached_df[gid]

        df = await download_sheet(gid)
        cached_df[gid] = df
        cached_time[gid] = now_time
        return cached_df[gid]

async def load_full_sheet():
    """Прогревает доступные вкладки текущего месяца."""
    dfs = []
    for day in [1, 16]:
        try:
            df = await load_sheet(day)
            dfs.append(df)
        except (ValueError, ConnectionError):
            pass  # GID не добавлен или таблица недоступна — пропускаем
    if not dfs:
        logging.warning("Нет доступных листов при старте — бот запустится без кэша.")
        return None
    await refresh_departments(force=True)
    return None

DEPARTMENTS_FALLBACK = {
    "👔 Менеджер": [
        "Рина Евгеньевна",
        "Нодира Комилджоновна",
        "Вадим Вячеславович",
    ],
    "🍽 Официант": [
        "Виталий",
        "Платон",
        "Юлия",
        "Владислав",
        "Злата",
        "Егор Капустин",
        "Егор Корниенков",
        "Кристина (наличка)",
    ],
    "🍸 Бармен": [
        "Вениамин",
        "Дарья",
    ],
    "💨 Кальян": [
        "Александр",
        "Никита Рафаэлович",
        "Дмитрий",
        "Андрей",
    ],
    "🙋 Хостес": [
        "Татьяна",
        "Мария",
        "Екатерина",
        "Дарья",
    ],
}

DEPARTMENTS: dict[str, list[str]] = DEPARTMENTS_FALLBACK.copy()
ALL_NAMES: list[str] = [n for names in DEPARTMENTS.values() for n in names]

_departments_updated_at: "datetime | None" = None
_DEPARTMENTS_TTL_SEC = 300


def parse_departments(df) -> dict:
    result: dict[str, list[str]] = {}
    current_role = None
    for i in range(len(df)):
        first = str(df.iloc[i, 0]).strip()
        if first in ROLES:
            current_role = first
            result[current_role] = []
            continue
        if current_role is None:
            continue
        name = clean_value(first)
        if name:
            result[current_role].append(_clean_person_name_value(name))
    return result


async def refresh_departments(force: bool = False) -> None:
    global DEPARTMENTS, ALL_NAMES, _departments_updated_at
    now = now_local()
    if (
        not force
        and _departments_updated_at is not None
        and (now - _departments_updated_at).total_seconds() < _DEPARTMENTS_TTL_SEC
    ):
        return
    try:
        df = await load_sheet(now.day)
        parsed = parse_departments(df)
        if not parsed:
            logging.warning("refresh_departments: пустой результат, оставляю fallback")
            return
        emoji_map = {label.split(" ", 1)[1]: label for label in DEPARTMENTS_FALLBACK}
        DEPARTMENTS = {
            emoji_map.get(role, role): names
            for role, names in parsed.items()
            if names
        }
        ALL_NAMES = [n for names in DEPARTMENTS.values() for n in names]
        _departments_updated_at = now
        logging.info("refresh_departments: %d ролей, %d сотрудников", len(DEPARTMENTS), len(ALL_NAMES))
    except (ValueError, ConnectionError) as e:
        logging.warning("refresh_departments: ошибка (%s), fallback активен", e)
    except Exception as e:
        logging.error("refresh_departments: неожиданная ошибка: %s", e)

# Словарь отделов с эмодзи — используется при отображении расписания
DEPT_EMOJIS: dict[str, str] = {
    "Менеджер": "👔 Менеджер",
    "Официант": "🍽 Официант",
    "Бармен":   "🍸 Бармен",
    "Кальян":   "💨 Кальян",
    "Хостес":   "🙋 Хостес",
}


ROLE_ORDER = ["Менеджеры", "Менеджер", "Официант", "Бармен", "Кальян", "Кальянщик", "Хостес"]

def role_display_label(role: str) -> str:
    """Красивое название роли/подразделения для вывода."""
    if not role:
        return ""

    role = str(role).strip()

    aliases = {
        "Менеджер": "Менеджеры",
        "Кальянщик": "Кальян",
    }
    display_role = aliases.get(role, role)

    emoji_map = {
        "Менеджеры": "👔 Менеджеры",
        "Официант": "🍽 Официант",
        "Бармен": "🍸 Бармен",
        "Кальян": "💨 Кальян",
        "Хостес": "🙋 Хостес",
    }

    return emoji_map.get(display_role, DEPT_EMOJIS.get(role, role))


def ordered_role_keys(people_by_role: dict) -> list:
    """Роли в стабильном порядке: сначала основные из таблицы, потом остальные."""
    keys = list(people_by_role.keys())
    result = []

    for role in ROLE_ORDER:
        if role in people_by_role and role not in result:
            result.append(role)

    for role in keys:
        if role not in result:
            result.append(role)

    return result



SCHEDULE_MAX_DAY_COL = 16  # B:P, правая часть листа содержит статистику, не график

ROLES = ["Менеджеры", "Менеджер", "Официант", "Бармен", "Кальян", "Хостес"]

MONTHS = [
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]

MONTHS_RU = {1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь", 7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"}


WELCOME_TEXT = (
    "Привет{name_part} 👋\n\n"
    "Я бот расписания — помогаю смотреть график и считать зарплату.\n\n"
    "📌 Мой график — сегодня, завтра, неделя или весь месяц\n"
    "👥 Коллеги — кто работает рядом, совпадение смен\n"
    "💰 Зарплата — примерный расчёт по ставке и учёт фактических часов\n"
    "🔔 Уведомления — о графике каждый день и напоминание внести часы\n\n"
    "{action}"
)

MONTHS_NOM = [
    "",
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
]

WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

RU_HOLIDAYS = {
    (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 7), (1, 8),
    (2, 23),
    (3, 8),
    (5, 1), (5, 9),
    (6, 12),
    (11, 4),
}

configure_keyboard_context(MONTHS, MONTHS_NOM, RU_HOLIDAYS)
configure_schedule_utils(MONTHS, RU_HOLIDAYS)

waiting_for_time = set()
selecting_own_name = set()
selecting_colleague = set()
viewing_colleague = {}
viewing_colleague_role: dict[int, str | None] = {}
_last_selected_dept: dict[int, str | None] = {}

comparing_users = set()
compare_selected = {}
compare_period = {}  # user_id -> (year, month, start_day, end_day)
user_week = {}  # хранит дни текущей недели для каждого пользователя

def main_kb(user_id, name: str = "Моё имя"):

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📌 Мой график"), KeyboardButton(text="📆 График сегодня/завтра")],
            [KeyboardButton(text="👀 Коллеги"), KeyboardButton(text="🔔 Уведомления")],
            [KeyboardButton(text="💰 Зарплата"), KeyboardButton(text=f"👤 {name}")],
        ],
        resize_keyboard=True
    )

async def main_kb_async(user_id: int) -> ReplyKeyboardMarkup:
    name = await get_user_name(user_id) or "Моё имя"
    return main_kb(user_id, name)


def salary_kb(track_hours: int = 0) -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton(text="📊 Примерная зарплата")]]
    if track_hours:
        keyboard += [
            [KeyboardButton(text="⏱ Внести смену"), KeyboardButton(text="📋 История смен")],
        ]
    keyboard += [
        [KeyboardButton(text="⚙️ Настройки учёта")],
        [KeyboardButton(text="🏠 Главное меню")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def salary_period_kb() -> ReplyKeyboardMarkup:
    now = now_local()
    month, year = now.month, now.year
    month_name = MONTHS_NOM[month]

    # Прошлый месяц
    if month == 1:
        prev_month, prev_year = 12, year - 1
    else:
        prev_month, prev_year = month - 1, year
    prev_month_name = MONTHS_NOM[prev_month]
    prev_end = calendar.monthrange(prev_year, prev_month)[1]
    cur_end = calendar.monthrange(year, month)[1]

    keyboard = [
        [KeyboardButton(text="📅 Текущий период")],
        [
            KeyboardButton(text="1-15 " + month_name),
            KeyboardButton(text="16-" + str(cur_end) + " " + month_name),
        ],
        [
            KeyboardButton(text="1-15 " + prev_month_name),
            KeyboardButton(text="16-" + str(prev_end) + " " + prev_month_name),
        ],
        [KeyboardButton(text="⬅️ Назад к зарплате")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def salary_settings_kb(track_hours: int = 0, notify_hours: int = 0) -> ReplyKeyboardMarkup:
    track_label = "🔴 Выключить учёт часов" if track_hours else "⬜ Включить учёт часов"
    notify_label = "🔔 Уведомление включено" if notify_hours else "🔕 Уведомление выключено"
    keyboard = [[KeyboardButton(text=track_label)]]
    if track_hours:
        keyboard += [
            [KeyboardButton(text=notify_label)],
            [KeyboardButton(text="🗑 Удалить смену из истории")],
        ]
    keyboard.append([KeyboardButton(text="⬅️ Назад к зарплате")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def shift_date_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📥 Сегодня"), KeyboardButton(text="📥 Вчера")],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True
    )


def shift_hours_kb(standard_hours) -> ReplyKeyboardMarkup:
    keyboard = []
    if standard_hours:
        keyboard.append([KeyboardButton(text="✅ Стандартная (" + str(standard_hours) + " ч)")])
    keyboard += [
        [KeyboardButton(text="✍️ Указать своё время")],
        [KeyboardButton(text="🏠 Главное меню")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def my_schedule_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📆 Завтра")],
            [KeyboardButton(text="🗓 Недели"), KeyboardButton(text="📋 Выбрать месяц")],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True
    )

def months_kb():
    """Динамически строит кнопки из SHEET_GID_MAP"""
    seen = set()
    buttons = []
    for (year, month, period) in sorted(SHEET_GID_MAP.keys()):
        key = (year, month)
        if key not in seen:
            seen.add(key)
            month_name = MONTHS_NOM[month]
            buttons.append([KeyboardButton(text=f"📋 {month_name} {year}")])
    buttons.append([KeyboardButton(text="🏠 Главное меню")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def today_tomorrow_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👥 Кто сегодня"), KeyboardButton(text="👥 Кто завтра")],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True
    )

def colleague_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📆 Завтра")],
            [KeyboardButton(text="🗓 Недели"), KeyboardButton(text="📋 Весь график")],
            [KeyboardButton(text="🤝 Совпадения")],
            [KeyboardButton(text="⬅️ Вернуться к себе")],
        ],
        resize_keyboard=True
    )






def dep_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👔 Менеджер"), KeyboardButton(text="🍽 Официант")],
            [KeyboardButton(text="🍸 Бармен"), KeyboardButton(text="💨 Кальян")],
            [KeyboardButton(text="🙋 Хостес")],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True
    )

def own_names_kb(department):
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=name)] for name in DEPARTMENTS[department]] + [[KeyboardButton(text="🏠 Главное меню")]],
        resize_keyboard=True
    )

async def colleague_names_kb(department, user_id):
    my_name = await get_user_name(user_id)
    buttons = []

    for name in DEPARTMENTS[department]:
        if name != my_name:
            buttons.append([KeyboardButton(text=f"👀 {name}")])

    buttons.append([KeyboardButton(text="🏠 Главное меню")])

    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

async def compare_names_kb(department, user_id):
    my_name = await get_user_name(user_id)
    selected = compare_selected.get(user_id, set())
    buttons = []

    for name in DEPARTMENTS[department]:
        if name == my_name:
            continue

        if name in selected:
            buttons.append([KeyboardButton(text=f"✅ {name}")])
        else:
            buttons.append([KeyboardButton(text=f"➕ {name}")])

    buttons.append([KeyboardButton(text="⬅️ Назад к сравнению")])
    buttons.append([KeyboardButton(text="🏠 Главное меню")])

    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def notifications_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔔 Включить"), KeyboardButton(text="🔕 Выключить")],
            [KeyboardButton(text="✍️ Задать время")],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True
    )

_MIN_LOADING_SEC = 0.8  # минимальное время показа «⏳ Загружаю...»

def with_loading(text="⏳ Загружаю..."):
    """Декоратор: показывает loading → хендлер → удаляет loading."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            event = args[0]
            if isinstance(event, CallbackQuery):
                msg_target = event.message
            else:
                msg_target = event
            loading = await msg_target.answer(text)
            t0 = asyncio.get_event_loop().time()
            try:
                return await func(*args, **kwargs)
            finally:
                elapsed = asyncio.get_event_loop().time() - t0
                if elapsed < _MIN_LOADING_SEC:
                    await asyncio.sleep(_MIN_LOADING_SEC - elapsed)
                try:
                    await loading.delete()
                except Exception:
                    pass
        return wrapper
    return decorator


async def loading_answer(message: Message, loading_text: str, coro_or_text, reply_markup=None):
    """Показывает loading_text, затем плавно заменяет на результат.
    Принимает корутину или готовую строку."""
    loading = await message.answer(loading_text)
    t0 = asyncio.get_event_loop().time()
    if asyncio.iscoroutine(coro_or_text):
        try:
            result = await coro_or_text
        except ConnectionError as e:
            result = str(e)
        except ValueError as e:
            result = f"📋 {e}"
        except Exception as e:
            logging.error(f"loading_answer: {e}\n{traceback.format_exc()}")
            result = "❌ Что-то пошло не так. Попробуй позже."
    else:
        result = coro_or_text

    elapsed = asyncio.get_event_loop().time() - t0
    if elapsed < _MIN_LOADING_SEC:
        await asyncio.sleep(_MIN_LOADING_SEC - elapsed)

    if reply_markup:
        # ReplyKeyboardMarkup нельзя добавить через edit_text —
        # удаляем loading и шлём один чистый ответ с клавиатурой
        try:
            await loading.delete()
        except Exception:
            pass
        await message.answer(str(result), reply_markup=reply_markup)
    else:
        # Без клавиатуры — редактируем на месте (плавно, без мерцания)
        try:
            await loading.edit_text(str(result))
        except Exception:
            try:
                await loading.delete()
            except Exception:
                pass
            await message.answer(str(result))

async def safe_schedule(coro):
    """Оборачивает вызов в try/except и возвращает текст ошибки если что-то пошло не так."""
    try:
        return await coro
    except ConnectionError as e:
        return str(e)
    except ValueError as e:
        return f"📋 {e}"
    except Exception as e:
        logging.error(f"Unexpected error: {e}\n{traceback.format_exc()}")
        return "❌ Что-то пошло не так. Попробуй позже."

def reset_modes(user_id):
    waiting_for_time.discard(user_id)
    selecting_own_name.discard(user_id)
    selecting_colleague.discard(user_id)
    viewing_colleague.pop(user_id, None)
    viewing_colleague_role.pop(user_id, None)
    viewing_colleague_role.pop(user_id, None)
    _last_selected_dept.pop(user_id, None)
    comparing_users.discard(user_id)
    compare_selected.pop(user_id, None)
    compare_period.pop(user_id, None)
    salary_mode.discard(user_id)
    shift_entering.pop(user_id, None)
    waiting_shift_hours.discard(user_id)
    _salary_period_data.pop(user_id, None)

def reset_compare_mode(user_id):
    comparing_users.discard(user_id)
    compare_selected.pop(user_id, None)

def selected_compare_text(user_id):
    selected = sorted(compare_selected.get(user_id, set()))

    if not selected:
        return "Выбранные сотрудники: пока никого."

    return "Выбранные сотрудники:\n" + "\n".join([f"• {name}" for name in selected])

def days_in_current_month():
    now = now_local()
    return calendar.monthrange(now.year, now.month)[1]


def is_day_published(day, month=None, year=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year
    has_gid = get_gid_for_day_month(day, month, year) is not None
    return has_gid


def weekday_label(day):
    now = now_local()
    weekday_index = datetime(now.year, now.month, day).weekday()
    label = WEEKDAYS[weekday_index]

    is_red = weekday_index in (4, 5) or (now.month, day) in RU_HOLIDAYS

    if is_red:
        return f"❗ {label}"

    return label


def unique_keep_order(items):
    """Убирает точные дубли, сохраняя порядок."""
    seen = set()
    result = []
    for item in items:
        key = str(item).strip()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result



def fmt_hours(h) -> str:
    """12.0 → '12', 12.5 → '12.5'"""
    h = float(h)
    return str(int(h)) if h == int(h) else str(h)




def is_valid_time(text):
    try:
        datetime.strptime(text.strip(), "%H:%M")
        return True
    except ValueError:
        return False

def get_day_column(df, day):
    for i in range(len(df)):
        first = str(df.iloc[i, 0]).strip()

        if first in ROLES:
            row = df.iloc[i].fillna("").astype(str).tolist()

            for col_index, value in enumerate(row[:SCHEDULE_MAX_DAY_COL + 1]):
                if str(value).strip() == str(day):
                    return col_index

    return None


def normalize_role_name(role: str | None) -> str | None:
    """Приводит роли из кнопок и Google Sheets к одному виду."""
    if role is None:
        return None

    text = str(role).replace("\xa0", " ").strip()
    if not text:
        return None

    aliases = {
        "Менеджер": "Менеджеры",
        "Менеджеры": "Менеджеры",
        "Официант": "Официант",
        "Официанты": "Официант",
        "Бармен": "Бармен",
        "Бармены": "Бармен",
        "Кальянщик": "Кальян",
        "Кальянщики": "Кальян",
        "Кальян": "Кальян",
        "Хостес": "Хостес",
    }

    return aliases.get(text, text)



def normalize_person_lookup_name(name: str | None) -> str:
    """Нормализация имени для поиска сотрудника в Google Sheets."""
    if name is None:
        return ""

    text = _clean_person_name_value(name)
    text = text.replace("ё", "е").replace("Ё", "Е")
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


async def find_row(name, day, month=None, year=None, target_role=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year
    df = await load_sheet(day, month, year)
    role = None
    target_role_norm = normalize_role_name(target_role)
    needle = str(name).strip().lower()
    needle_norm = normalize_person_lookup_name(name)

    for i in range(len(df)):
        first = str(df.iloc[i, 0]).strip()
        if first in ROLES:
            role = normalize_role_name(first)
            continue
        row = df.iloc[i].fillna("").astype(str).tolist()
        if needle and needle in " ".join(row).lower():
            if target_role_norm is None or role == target_role_norm:
                return row, role

    # Fallback: точный поиск по первой колонке с нормализацией имени.
    # Нужен для листов 16-30, где роль/строка может отличаться от выбранной кнопки.
    role = None
    for i in range(len(df)):
        first = str(df.iloc[i, 0]).replace("\xa0", " ").strip()
        first_clean = _clean_person_name_value(first)

        if first in ROLES:
            role = normalize_role_name(first)
            continue

        if not first_clean:
            continue

        first_norm = normalize_person_lookup_name(first_clean)
        if first_norm == needle_norm:
            if target_role_norm is None or role == target_role_norm:
                row = df.iloc[i].fillna("").astype(str).tolist()
                logging.info(
                    "find_row fallback matched name=%s day=%s month=%s year=%s role=%s target_role=%s",
                    name, day, month, year, role, target_role_norm,
                )
                return row, role

    return None, None


async def get_day_value(row, day, month=None, year=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year
    df = await load_sheet(day, month, year)
    col = get_day_column(df, day)

    if col is None or col >= len(row):
        return ""

    return row[col]


async def get_people_for_day(day, month=None, year=None):
    """
    Возвращает всех работающих за день по всем подразделениям Google Sheets.

    Поддерживает листы, где внутри одного листа есть несколько блоков с повторными строками дат.
    Например: Менеджеры/Официанты/Бармены, потом ниже Кальян со своим заголовком дат.
    """
    now = now_local()
    month = month or now.month
    year = year or now.year

    try:
        df = await load_sheet(day, month, year)
    except Exception as e:
        logging.exception("get_people_for_day: ошибка load_sheet day=%s month=%s year=%s: %s", day, month, year, e)
        return {}

    role_aliases = {
        "менеджеры": "Менеджеры",
        "менеджер": "Менеджеры",
        "официант": "Официант",
        "официанты": "Официант",
        "бармен": "Бармен",
        "бармены": "Бармен",
        "кальян": "Кальян",
        "кальянщик": "Кальян",
        "кальянщики": "Кальян",
        "хостес": "Хостес",
    }

    weekdays = {"вт", "ср", "чт", "пт", "сб", "вс", "пн"}

    def detect_role_from_cell(value):
        text = str(value or "").replace("\xa0", " ").strip()
        text_norm = re.sub(r"\s+", " ", text).lower()
        return role_aliases.get(text_norm)

    def find_day_col_in_row(row_idx: int):
        """Если строка содержит номер нужного дня, возвращает колонку."""
        try:
            for col in range(1, min(len(df.columns), SCHEDULE_MAX_DAY_COL + 1)):
                cell = df.iat[row_idx, col]
                cell_text = clean_value(cell)
                if cell_text == str(day):
                    return col
        except Exception:
            return None
        return None

    result = {}
    current_role = None
    current_day_col = None

    # Начальный fallback: старый способ, если строка дат ещё не встретилась.
    try:
        current_day_col = get_day_column(df, day)
    except Exception:
        current_day_col = None

    for i in range(len(df)):
        raw_first = df.iat[i, 0] if len(df.columns) > 0 else ""
        first_text = str(raw_first or "").replace("\xa0", " ").strip()

        # 1. Колонку дня берём один раз через get_day_column(df, day).
        # Не обновляем её по строкам ниже: в правом блоке статистики есть числа,
        # которые можно ошибочно принять за дни графика.
        # row_day_col = find_day_col_in_row(i)

        if not first_text or first_text.lower() == "nan":
            continue

        # 2. Если это заголовок подразделения, меняем текущую роль.
        detected_role = detect_role_from_cell(first_text)
        if detected_role:
            current_role = detected_role
            result.setdefault(current_role, [])

            # Часто сразу следующая строка после роли содержит даты.
            # Но если дата уже есть в этой строке, current_day_col уже обновился выше.
            continue

        if not current_role or current_day_col is None:
            continue

        name = _clean_person_name_value(first_text)
        if not name:
            continue

        lower_name = name.lower().strip()

        # 3. Пропускаем служебные строки.
        if lower_name in weekdays:
            continue
        if lower_name.isdigit():
            continue
        if "кол-во" in lower_name or "смен" in lower_name:
            continue
        if lower_name in role_aliases:
            continue

        try:
            value = df.iat[i, current_day_col]
        except Exception:
            continue

        if not is_work_shift(value):
            continue

        result.setdefault(current_role, [])
        result[current_role].append(f"{name} — {detect_shift(value)}")

    cleaned = {}
    for role, people in result.items():
        people = unique_keep_order(people) if "unique_keep_order" in globals() else list(dict.fromkeys(people))
        if people:
            cleaned[role] = people

    logging.info(
        "get_people_for_day: day=%s month=%s year=%s roles=%s total=%s",
        day, month, year, {k: len(v) for k, v in cleaned.items()}, sum(len(v) for v in cleaned.values())
    )

    return cleaned



async def get_common_day_off_people(name, day, month=None, year=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year
    df = await load_sheet(day, month, year)
    col = get_day_column(df, day)

    if col is None:
        return []

    result = []
    for i in range(len(df)):
        first = str(df.iloc[i, 0]).strip()
        if first in ROLES:
            continue
        row = df.iloc[i].fillna("").astype(str).tolist()
        if len(row) <= col:
            continue
        person_name = clean_value(row[0])
        value = row[col]
        if person_name and person_name != name and not is_work_shift(value):
            result.append(clean_person_name(person_name))

    return result

async def get_my_status_for_day(user_id, day, month=None, year=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year
    _user = await get_user(user_id)
    my_name = _user[1] if _user else None
    my_role = _user[4] if _user else None

    if not my_name:
        return "👤 Твоё имя не выбрано."

    if not is_day_published(day, month, year):
        return "👤 Твой график: график пока не составлен."

    row, _ = await find_row(my_name, day, month, year, target_role=my_role)
    if not row:
        return f"👤 Твой график: не нашёл имя {my_name}."

    value = await get_day_value(row, day, month, year)
    if is_work_shift(value):
        return f"✅ Ты работаешь: {detect_shift(value)}"

    return "🏖 Ты отдыхаешь."

async def get_day_schedule(name, day, month=None, year=None, target_role=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year

    max_day = calendar.monthrange(year, month)[1]

    if day > max_day:
        return "Такой даты в этом месяце нет."

    if not is_day_published(day, month, year):
        return f"{name}\n\n{format_date(day, month, year)} — график пока не составлен"

    row, role = await find_row(name, day, month, year, target_role=target_role)

    if not row:
        return f"Не нашёл график для: {name}"

    role_text = f"\n{DEPT_EMOJIS.get(role, role)}" if role else ""
    value = await get_day_value(row, day, month, year)
    if is_work_shift(value):
        header = f"{format_date(day, month, year)} — {name} работает ✅"
        shift_line = f"Смена: {detect_shift(value)}"
    else:
        header = f"{format_date(day, month, year)} — {name} отдыхает 🏖"
        shift_line = ""

    role_suffix = role_text.strip() if role_text else ""
    text = header
    if role_suffix:
        text += f"  ({role_suffix})"
    if shift_line:
        text += f"\n{shift_line}"

    people_by_role = await get_people_for_day(day, month, year)
    coworkers_parts = []
    for role_key in ordered_role_keys(people_by_role):
        people = people_by_role.get(role_key, [])
        if not people:
            continue
        coworkers_parts.append(role_display_label(role_key))
        coworkers_parts.extend(people)
        coworkers_parts.append("")
    coworkers_text = "\n".join(coworkers_parts).strip()
    total_on_shift = sum(len(v) for v in people_by_role.values())
    if coworkers_text:
        text += f"\n\n👥 {format_date(day, month, year)} работают: всего {total_on_shift}\n\n" + coworkers_text.strip()

    if not is_work_shift(value):
        common_off = await get_common_day_off_people(name, day, month, year)
        if common_off:
            text += f"\n\n🏖 {format_date(day, month, year)} вместе отдыхают:\n" + "\n".join(unique_keep_order(common_off))

    return text


async def get_range_schedule(name, start_day, end_day, month=None, year=None, target_role=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year

    max_day = calendar.monthrange(year, month)[1]
    end_day = min(end_day, max_day)

    result = [name]
    saved_role = None
    found_any = False
    role_line_index = None
    unpublished_start = None

    for day in range(start_day, end_day + 1):
        if not is_day_published(day, month, year):
            if unpublished_start is None:
                unpublished_start = day
            continue

        if unpublished_start is not None:
            if role_line_index is None:
                result.append("")
                role_line_index = 1
                result.append("")
            if unpublished_start == day - 1:
                result.append(f"{unpublished_start} {MONTHS[month]} — график пока не составлен")
            else:
                result.append(f"{unpublished_start}–{day - 1} {MONTHS[month]} — график пока не составлен")
            unpublished_start = None

        row, role = await find_row(name, day, month, year, target_role=target_role)

        if row:
            found_any = True
            if role:
                saved_role = role
            value = await get_day_value(row, day, month, year)
        else:
            value = ""

        if role_line_index is None:
            result.append(DEPT_EMOJIS.get(saved_role or role or '', saved_role or role or ''))
            role_line_index = 1
            result.append("")

        result.append(f"{format_date(day, month, year)} — {detect_shift(value)}")

    if unpublished_start is not None:
        if role_line_index is None:
            result.append(DEPT_EMOJIS.get(saved_role or '', saved_role or ''))
            role_line_index = 1
            result.append("")
        if unpublished_start == end_day:
            result.append(f"{unpublished_start} {MONTHS[month]} — график пока не составлен")
        else:
            result.append(f"{unpublished_start}–{end_day} {MONTHS[month]} — график пока не составлен")

    if not found_any:
        return f"Не нашёл график для: {name}"

    if saved_role and role_line_index is not None:
        result[role_line_index] = DEPT_EMOJIS.get(saved_role, saved_role)

    return "\n".join(result)


async def get_people(day, user_id, month=None, year=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year
    max_day = calendar.monthrange(year, month)[1]

    if day > max_day:
        return "Такой даты в этом месяце нет."

    my_status = await get_my_status_for_day(user_id, day, month, year)

    if not is_day_published(day, month, year):
        return f"👥 {format_date(day, month, year)}\n\n{my_status}\n\nГрафик на этот период пока не составлен."

    result = await get_people_for_day(day, month, year)

    total = sum(len(v) for v in result.values())
    text = f"👥 {format_date(day, month, year)} работают: всего {total}\n\n"
    text += my_status + "\n\n"

    has_any = False
    for role_key in ordered_role_keys(result):
        people = result.get(role_key, [])
        if people:
            has_any = True
            label = role_display_label(role_key)
            text += f"{label} ({len(people)})\n" + "\n".join(people) + "\n\n"

    if not has_any:
        text += "Никто не работает."

    return text.strip()

async def find_next_shift(name, from_day, from_month=None, from_year=None, target_role=None):
    """Ищет следующую смену начиная с from_day, переходит через месяц если нужно."""
    now = now_local()
    if from_month is None:
        from_month = now.month
    if from_year is None:
        from_year = now.year

    # Смотрим вперёд на 45 дней максимум
    from datetime import date
    start = date(from_year, from_month, from_day)

    for offset in range(1, 46):
        target = start + timedelta(days=offset)
        d, m, y = target.day, target.month, target.year

        if not is_day_published(d, m, y):
            continue

        try:
            row, _ = await find_row(name, d, m, y, target_role=target_role)
            if not row:
                continue
            value = await get_day_value(row, d, m, y)
            if is_work_shift(value):
                return target, value
        except ValueError:
            continue

    return None, None

async def get_notification_text(name, target_role=None):
    now = now_local()
    today = now.day
    month = now.month
    year = now.year

    if not is_day_published(today, month, year):
        next_dt, next_value = await find_next_shift(name, today, month, year, target_role=target_role)
        if next_dt:
            from datetime import date
            today_date = date(year, month, today)
            off_days = (next_dt - today_date).days
            return (
                f"🔔 Ежедневное уведомление\n\n"
                f"{name}\n"
                f"{format_date(today, month, year)}\n"
                f"📋 График пока не составлен\n\n"
                f"Ближайшая смена: {format_date(next_dt.day, next_dt.month, next_dt.year)} — {detect_shift(next_value)}\n"
                f"До неё: {off_days} дн."
            )
        return None

    row, _ = await find_row(name, today, month, year, target_role=target_role)
    if not row:
        return None

    value = await get_day_value(row, today, month, year)

    if is_work_shift(value):
        people_by_role = await get_people_for_day(today, month, year)
        total = sum(len(v) for v in people_by_role.values())
        return (
            f"🔔 Ежедневное уведомление\n\n"
            f"{name}\n"
            f"{format_date(today, month, year)}\n"
            f"✅ Сегодня ты работаешь: {detect_shift(value)}\n"
            f"👥 На смене: {total} чел."
        )

    next_dt, next_value = await find_next_shift(name, today, month, year, target_role=target_role)
    common_off = await get_common_day_off_people(name, today, month, year)

    text = (
        f"🔔 Ежедневное уведомление\n\n"
        f"{name}\n"
        f"{format_date(today, month, year)}\n"
        f"🏖 Сегодня ты отдыхаешь"
    )

    if next_dt:
        from datetime import date
        today_date = date(year, month, today)
        off_days = (next_dt - today_date).days
        text += (
            f"\n\nДо ближайшей смены: {off_days} дн.\n"
            f"Ближайшая смена: {format_date(next_dt.day, next_dt.month, next_dt.year)} — {detect_shift(next_value)}"
        )
    else:
        text += "\n\nБлижайшей смены в актуальном графике пока нет."

    if common_off:
        text += "\n\n🏖 Сегодня вместе с тобой отдыхают:\n" + "\n".join(common_off)

    return text

async def compare_multiple(user_id):
    user = await get_user(user_id)
    if not user or not user[1]:
        return "Сначала выбери своё имя."

    my_name = user[1]
    selected = sorted(compare_selected.get(user_id, set()))
    if not selected:
        return "Добавь хотя бы одного сотрудника для сравнения."

    all_people = [my_name] + selected

    period = compare_period.get(user_id)
    if period:
        year, month, period_start, period_end = period
    else:
        period_start, period_end = current_period()
        now = now_local()
        month, year = now.month, now.year

    common_work = []
    common_off = []

    for day in range(period_start, period_end + 1):
        values = {}

        for name in all_people:
            target_role = None
            for dep_label, names in DEPARTMENTS.items():
                if name in names:
                    parts = dep_label.split(" ", 1)
                    target_role = parts[1] if len(parts) == 2 else dep_label
                    break

            row = None
            try:
                row, _ = await find_row(name, day, month, year, target_role=target_role)
            except (ValueError, ConnectionError) as e:
                logging.warning(
                    "compare_multiple: поиск с ролью не дал данных name=%s day=%s month=%s year=%s role=%s: %s",
                    name, day, month, year, target_role, e,
                )
            except Exception as e:
                logging.exception(
                    "compare_multiple: ошибка поиска с ролью name=%s day=%s month=%s year=%s role=%s: %s",
                    name, day, month, year, target_role, e,
                )

            if not row and target_role:
                try:
                    row, _ = await find_row(name, day, month, year, target_role=None)
                    if row:
                        logging.info(
                            "compare_multiple: fallback без роли сработал name=%s day=%s month=%s year=%s old_role=%s",
                            name, day, month, year, target_role,
                        )
                except (ValueError, ConnectionError) as e:
                    logging.warning(
                        "compare_multiple: fallback без роли не дал данных name=%s day=%s month=%s year=%s: %s",
                        name, day, month, year, e,
                    )
                except Exception as e:
                    logging.exception(
                        "compare_multiple: ошибка fallback без роли name=%s day=%s month=%s year=%s: %s",
                        name, day, month, year, e,
                    )

            if not row:
                logging.warning(
                    "compare_multiple: сотрудник не найден name=%s day=%s month=%s year=%s role=%s",
                    name, day, month, year, target_role,
                )
                continue

            values[name] = await get_day_value(row, day, month, year)

        if len(values) < len(all_people):
            continue

        if all(is_work_shift(v) for v in values.values()):
            shifts_text = " / ".join(
                f"{name}: {detect_shift(values[name])}" for name in all_people
            )
            common_work.append(f"{format_date(day, month, year)} — {shifts_text}")
        elif all(not is_work_shift(v) for v in values.values()):
            common_off.append(format_date(day, month, year))

    month_name = _month_label_for_period(month)

    text = "🤝 Совпадения по группе\n\n"
    text += "Участники:\n" + "\n".join(f"• {name}" for name in all_people)
    text += f"\n\nПериод: {period_start}–{period_end} {month_name} {year}\n\n"
    text += "✅ Все работают:\n" + ("\n".join(common_work) if common_work else "нет")
    text += "\n\n🏖 Все отдыхают:\n" + ("\n".join(common_off) if common_off else "нет")
    return text


async def active_name(user_id):
    if user_id in viewing_colleague:
        return viewing_colleague[user_id]

    return await get_user_name(user_id)


async def active_role(user_id):
    """Роль активного пользователя/коллеги для find_row."""
    if user_id in viewing_colleague:
        return viewing_colleague_role.get(user_id)
    user = await get_user(user_id)
    return user[4] if user else None

async def hours_notification_loop(bot) -> None:
    sent = {}
    last_cleanup = now_local().date()

    while True:
        try:
            now = now_local()
            current_time = now.strftime("%H:%M")

            # Чистим sent раз в день — удаляем ключи старше 2 дней
            today_date = now.date()
            if today_date != last_cleanup:
                cutoff = (today_date - timedelta(days=2)).strftime("%Y-%m-%d")
                sent = {k: v for k, v in sent.items()
                        if k.split("-hours-")[-1] >= cutoff}
                last_cleanup = today_date

            # Ночные уведомления (до 12:00) — смена была ВЧЕРА
            if now.hour < 12:
                shift_dt = now - timedelta(days=1)
            else:
                shift_dt = now

            shift_day   = shift_dt.day
            shift_month = shift_dt.month
            shift_year  = shift_dt.year
            shift_key   = shift_dt.strftime("%Y-%m-%d")
            day_type    = get_day_type(shift_dt)

            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT user_id, name, role FROM users "
                    "WHERE notify_hours=1 AND name IS NOT NULL"
                )
                users = cursor.fetchall()
                cursor.close()
                conn.close()
            except Exception as e:
                logging.error("hours_notification_loop DB error: %s", e)
                await asyncio.sleep(60)
                continue

            for _hr in users:
                user_id, name = _hr[0], _hr[1]
                _hr_role = _hr[2] if len(_hr) > 2 else None
                key = f"{user_id}-hours-{shift_key}"
                if sent.get(key):
                    continue

                try:
                    if not is_day_published(shift_day, shift_month, shift_year):
                        continue

                    row, _ = await find_row(name, shift_day, shift_month, shift_year, target_role=_hr_role)
                    if not row:
                        continue

                    value = await get_day_value(row, shift_day, shift_month, shift_year)
                    if not is_work_shift(value):
                        continue

                    shift_type = detect_shift_type(value)
                    if not shift_type:
                        continue

                    notify_time = SHIFT_END_NOTIFY.get((shift_type, day_type))
                    if not notify_time or notify_time != current_time:
                        continue

                    existing = await get_shift_for_date(user_id, shift_key)
                    if existing:
                        sent[key] = True
                        continue

                    shift_label = {"morning": "утро", "evening": "вечер"}.get(shift_type, "")
                    std_hours = get_standard_hours(shift_type, shift_dt)
                    lines = ["⏱ Не забудь внести часы за смену!"]

                    if shift_label:
                        line = f"По графику {shift_day} {MONTHS[shift_month]}: {shift_label}"
                        if std_hours:
                            line += f", стандартная смена — {std_hours} ч"
                        lines.append(line)

                    await bot.send_message(user_id, "\n".join(lines))
                    sent[key] = True

                except Exception as e:
                    logging.exception("hours_notification_loop error for user_id=%s name=%s: %s", user_id, name, e)

        except Exception as e:
            logging.exception("hours_notification_loop: критическая ошибка цикла: %s", e)

        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            break



async def notification_loop(bot):
    sent = {}
    last_cleanup = now_local().date()
    last_dept_refresh = now_local()

    while True:
        now = now_local()
        current_time = now.strftime("%H:%M")

        # Обновляем состав отделов раз в час
        if (now - last_dept_refresh).total_seconds() > 3600:
            try:
                await refresh_departments(force=True)
                last_dept_refresh = now
                logging.info("refresh_departments: обновлено")
            except Exception as e:
                logging.warning("refresh_departments error: %s", e)
        today_key = now.strftime("%Y-%m-%d")

        # Чистим sent раз в день — удаляем ключи старше 2 дней
        today_date = now.date()
        if today_date != last_cleanup:
            cutoff = (today_date - timedelta(days=2)).strftime("%Y-%m-%d")
            # Ключ вида "user_id-YYYY-MM-DD-HH:MM" — берём дату через split
            sent = {k: v for k, v in sent.items()
                    if k.split("-", 1)[1][:10] >= cutoff}
            last_cleanup = today_date

        for _nr in await get_notify_users():
            user_id, name, notify_time = _nr[0], _nr[1], _nr[2]
            _nr_role = _nr[3] if len(_nr) > 3 else None
            if notify_time != current_time:
                continue

            key = f"{user_id}-{today_key}-{notify_time}"

            if sent.get(key):
                continue

            try:
                text = await get_notification_text(name, target_role=_nr_role)

                if text:
                    await bot.send_message(user_id, text)
                    sent[key] = True
                else:
                    logging.warning(
                        "notification_loop: пустой текст уведомления user_id=%s name=%s notify_time=%s role=%s",
                        user_id, name, notify_time, _nr_role,
                    )
            except Exception as e:
                logging.exception(
                    "notification_loop: ошибка отправки user_id=%s name=%s notify_time=%s role=%s: %s",
                    user_id, name, notify_time, _nr_role, e,
                )

        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            break


@dp.message(F.text == "/health")
async def admin_health(message: Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    now = now_local()
    db_status = "unknown"
    notify_count = "?"
    notify_hours_count = "?"

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE notify=1")
        notify_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM users WHERE notify_hours=1")
        notify_hours_count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"

    text = (
        "🛠 Health check\n\n"
        f"Время бота: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Таймзона: {APP_TIMEZONE_NAME}\n"
        f"БД: {db_status}\n"
        f"Пользователей с уведомлениями смен: {notify_count}\n"
        f"Пользователей с уведомлениями часов: {notify_hours_count}\n"
        f"Периодов в SHEET_GID_MAP: {len(SHEET_GID_MAP)}\n"
        f"Кэшированных gid: {len(cached_df)}\n"
    )
    await message.answer(text)


@dp.message(F.text == "/periods")
async def admin_periods(message: Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    actual = set(get_available_periods())
    lines = ["📅 Периоды графика\n"]
    for year, month, start_day in sorted(SHEET_GID_MAP.keys()):
        if start_day == 1:
            end_day = 15
        else:
            end_day = calendar.monthrange(year, month)[1]
        status = "актуален" if (year, month, start_day, end_day) in actual else "прошёл"
        gid = SHEET_GID_MAP[(year, month, start_day)]
        lines.append(
            f"{start_day}–{end_day} {_month_label_for_period(month)} {year}: gid={gid} ({status})"
        )

    await message.answer("\n".join(lines))


@dp.message(F.text == "/cache")
async def admin_cache(message: Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    now = now_local()
    if not cached_df:
        return await message.answer("🧹 Кэш Google Sheets пуст.")

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

    await message.answer("\n".join(lines))


@dp.message(F.text == "/reload_sheets")
async def admin_reload_sheets(message: Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    clear_sheet_cache()
    try:
        await load_full_sheet()
        await message.answer("✅ Кэш Google Sheets сброшен и таблицы загружены заново.")
    except Exception as e:
        logging.exception("admin_reload_sheets error: %s", e)
        await message.answer(f"⚠️ Кэш сброшен, но загрузка таблиц завершилась ошибкой: {e}")



@dp.message(CommandStart())
@with_loading("⏳ Загружаю...")
async def start(message: Message):
    user_id = message.from_user.id
    reset_modes(user_id)

    user = await get_user(user_id)

    if user and user[1]:
        await message.answer(
            WELCOME_TEXT.format(
            name_part=f", {user[1]}",
            action="Выбери раздел 👇"
        ),
            reply_markup=await main_kb_async(user_id)
        )
    else:
        await message.answer(
            WELCOME_TEXT.format(
                name_part="",
                action="Для начала выбери своё имя — нажми 📌 Мой график."
            ),
            reply_markup=await main_kb_async(user_id)
        )
        selecting_own_name.add(user_id)

@dp.message(F.text == "🏠 Главное меню")
@with_loading("⏳ Загружаю...")
async def home(message: Message):
    user_id = message.from_user.id
    reset_modes(user_id)

    name = await get_user_name(user_id)
    greeting = f"Привет, {name} 👋" if name else "🏠 Главное меню"
    await message.answer(greeting, reply_markup=await main_kb_async(user_id))

@dp.message(F.text == "📌 Мой график")
async def my_schedule_menu(message: Message):
    user_id = message.from_user.id
    viewing_colleague.pop(user_id, None)
    viewing_colleague_role.pop(user_id, None)
    reset_compare_mode(user_id)

    name = await active_name(user_id)
    loading = await message.answer("⏳ Загружаю твой график...")
    t0 = asyncio.get_event_loop().time()

    _ms_role = await active_role(user_id)
    today_line = ""
    if name:
        now = now_local()
        try:
            row, _ = await find_row(name, now.day, now.month, now.year, target_role=_ms_role)
            if row:
                value = await get_day_value(row, now.day, now.month, now.year)
                if is_work_shift(value):
                    today_line = f"\n\n📅 Сегодня работаешь — {detect_shift(value)}"
                else:
                    today_line = "\n\n🏖 Сегодня выходной"
            else:
                today_line = "\n\n📋 График на сегодня ещё не составлен"
        except Exception:
            pass

    elapsed = asyncio.get_event_loop().time() - t0
    if elapsed < _MIN_LOADING_SEC:
        await asyncio.sleep(_MIN_LOADING_SEC - elapsed)
    try:
        await loading.delete()
    except Exception:
        pass
    await message.answer(f"📌 Мой график{today_line}", reply_markup=my_schedule_kb())

@dp.message(F.text == "📆 График сегодня/завтра")
async def today_tomorrow_menu(message: Message):
    await message.answer("📆 График сегодня/завтра:", reply_markup=today_tomorrow_kb())

@dp.message(F.text == "⬅️ Вернуться к себе")
@with_loading("⏳ Загружаю...")
async def back_to_self(message: Message):
    user_id = message.from_user.id
    viewing_colleague.pop(user_id, None)
    viewing_colleague_role.pop(user_id, None)
    reset_compare_mode(user_id)

    name = await get_user_name(user_id) or "не выбрано"

    await message.answer(
        f"👤 Твой график — {name}",
        reply_markup=await main_kb_async(user_id)
    )

@dp.message(F.text == "⬅️ Назад к коллеге")
async def back_to_colleague(message: Message):
    user_id = message.from_user.id
    comparing_users.discard(user_id)

    colleague_name = viewing_colleague.get(user_id)

    if not colleague_name:
        return await message.answer("Коллега не выбран.", reply_markup=await main_kb_async(user_id))

    await message.answer(
        f"👀 Ты смотришь график коллеги: {colleague_name}",
        reply_markup=colleague_kb()
    )

@dp.message(F.text == "⬅️ Назад к сравнению")
async def back_to_compare(message: Message):
    user_id = message.from_user.id

    await message.answer(
        "🤝 Сравнение графиков\n\n" + selected_compare_text(user_id),
        reply_markup=compare_kb()
    )

@dp.message(F.text.startswith("👤 "))
async def choose_own_name(message: Message):
    user_id = message.from_user.id

    waiting_for_time.discard(user_id)
    selecting_colleague.discard(user_id)
    viewing_colleague.pop(user_id, None)
    viewing_colleague_role.pop(user_id, None)
    reset_compare_mode(user_id)
    selecting_own_name.add(user_id)

    await message.answer("Выбери своё подразделение:", reply_markup=dep_kb())

@dp.message(F.text == "👀 Коллеги")
async def choose_colleague_department(message: Message):
    user_id = message.from_user.id

    waiting_for_time.discard(user_id)
    selecting_own_name.discard(user_id)
    reset_compare_mode(user_id)
    selecting_colleague.add(user_id)

    await message.answer("Выбери подразделение коллеги:", reply_markup=dep_kb())

@dp.message(F.text == "➕ Добавить сотрудника")
async def add_compare_person(message: Message):
    user_id = message.from_user.id
    comparing_users.add(user_id)

    await message.answer("Выбери подразделение сотрудника:", reply_markup=dep_kb())

@dp.message(F.text.func(lambda t: t is not None and t in DEPARTMENTS))
async def department_selected(message: Message):
    user_id = message.from_user.id
    department = message.text

    parts = department.split(" ", 1)
    _last_selected_dept[user_id] = parts[1] if len(parts) == 2 else department

    if user_id in comparing_users:
        await message.answer("Выбери сотрудника для сравнения:", reply_markup=await compare_names_kb(department, user_id))
    elif user_id in selecting_colleague:
        await message.answer("Выбери коллегу:", reply_markup=await colleague_names_kb(department, user_id))
    else:
        selecting_own_name.add(user_id)
        await message.answer("Выбери своё имя:", reply_markup=own_names_kb(department))

@dp.message(F.text.func(lambda t: t is not None and t in ALL_NAMES))
@with_loading("⏳ Сохраняю...")
async def own_name_selected(message: Message):
    user_id = message.from_user.id

    user_role = _last_selected_dept.pop(user_id, None)
    if not user_role:
        for dept_label, names in DEPARTMENTS.items():
            if message.text in names:
                parts = dept_label.split(" ", 1)
                user_role = parts[1] if len(parts) == 2 else dept_label
                break

    await save_user(user_id, name=message.text, notify=0, notify_time='', role=user_role)
    reset_modes(user_id)

    await message.answer(
        f"✅ Готово! Теперь ты — {message.text}",
        reply_markup=await main_kb_async(user_id)
    )

@dp.message(F.text.startswith("👀 "))
async def colleague_selected(message: Message):
    user_id = message.from_user.id
    colleague_name = message.text.replace("👀 ", "").strip()

    viewing_colleague[user_id] = colleague_name
    viewing_colleague_role[user_id] = _last_selected_dept.pop(user_id, None)
    selecting_colleague.discard(user_id)

    compare_selected[user_id] = {colleague_name}

    await message.answer(
        f"👀 Ты смотришь график коллеги: {colleague_name}",
        reply_markup=colleague_kb()
    )

@dp.message(F.text.startswith("➕ "))
@with_loading("⏳ Загружаю...")
async def compare_person_selected(message: Message):
    user_id = message.from_user.id
    name = message.text.replace("➕ ", "").strip()

    my_name = await get_user_name(user_id)

    if name == my_name:
        return await message.answer("Себя добавлять не нужно — ты уже участвуешь в сравнении.")

    if user_id not in compare_selected:
        compare_selected[user_id] = set()

    compare_selected[user_id].add(name)

    await message.answer(
        f"Добавил: {name}\n\n" + selected_compare_text(user_id),
        reply_markup=compare_kb()
    )

@dp.message((F.text.startswith("✅ ")) & (F.text != "✅ Посчитать совпадения") & (~F.text.startswith("✅ Стандартная (")) )
async def compare_person_already_selected(message: Message):
    user_id = message.from_user.id
    name = message.text.replace("✅ ", "").strip()

    await message.answer(
        f"{name} уже выбран.\n\n" + selected_compare_text(user_id),
        reply_markup=compare_kb()
    )

@dp.message(F.text == "🤝 Совпадения")
async def compare_menu(message: Message):
    user_id = message.from_user.id

    colleague_name = viewing_colleague.get(user_id)

    if not colleague_name:
        return await message.answer(
            "Сначала выбери коллегу через раздел «👀 Коллеги».",
            reply_markup=await main_kb_async(user_id)
        )

    comparing_users.add(user_id)

    if user_id not in compare_selected:
        compare_selected[user_id] = {colleague_name}
    else:
        compare_selected[user_id].add(colleague_name)

    await message.answer(
        "🤝 Сравнение графиков\n\n" + selected_compare_text(user_id),
        reply_markup=compare_kb()
    )


@dp.message(F.text == "✅ Посчитать совпадения")
async def ask_compare_period(message: Message):
    user_id = message.from_user.id

    if user_id not in comparing_users:
        comparing_users.add(user_id)

    selected = compare_selected.get(user_id, set())
    if not selected:
        return await message.answer(
            "Добавь хотя бы одного сотрудника для сравнения.",
            reply_markup=compare_kb()
        )

    periods = get_available_periods()
    if not periods:
        return await message.answer(
            "❌ Нет доступных актуальных периодов. Добавь gid периода в SHEET_GID_MAP.",
            reply_markup=compare_kb()
        )

    if len(periods) == 1:
        compare_period[user_id] = periods[0]
        return await loading_answer(
            message,
            "⏳ Считаю совпадения...",
            compare_multiple(user_id),
            reply_markup=compare_kb()
        )

    await message.answer(
        "📅 Выбери период для сравнения:",
        reply_markup=compare_period_kb()
    )




@dp.message(F.text == "⬅️ Назад к сравнению")
async def back_to_compare_from_period(message: Message):
    user_id = message.from_user.id
    if user_id in comparing_users:
        await message.answer("🤝 Выбери сотрудников для сравнения:", reply_markup=compare_kb())


@dp.message(F.text.regexp(r"^📅 \d+–\d+ .+ \d{4}$"))
async def handle_compare_period_select(message: Message):
    user_id = message.from_user.id

    if user_id not in comparing_users:
        return

    m = re.match(r"^📅 (\d+)–(\d+) (.+) (\d{4})$", message.text)
    if not m:
        return

    start_day = int(m.group(1))
    end_day = int(m.group(2))
    month_name = m.group(3).strip()
    year = int(m.group(4))

    matched = None
    for period in get_available_periods():
        p_year, p_month, p_start, p_end = period
        if (
            p_year == year
            and p_start == start_day
            and p_end == end_day
            and _month_label_for_period(p_month) == month_name
        ):
            matched = period
            break

    if not matched:
        return await message.answer(
            "❌ Период не найден или уже не актуален.",
            reply_markup=compare_period_kb()
        )

    compare_period[user_id] = matched

    await loading_answer(
        message,
        "⏳ Считаю совпадения...",
        compare_multiple(user_id),
        reply_markup=compare_kb()
    )


@dp.message(F.text == "🧹 Очистить выбранных")
async def clear_compare(message: Message):
    user_id = message.from_user.id

    colleague_name = viewing_colleague.get(user_id)

    if colleague_name:
        compare_selected[user_id] = {colleague_name}
    else:
        compare_selected[user_id] = set()

    await message.answer(
        "Выбранные сотрудники очищены.\n\n" + selected_compare_text(user_id),
        reply_markup=compare_kb()
    )

@dp.message(F.text == "📅 Сегодня")
async def today(message: Message):
    name = await active_name(message.from_user.id)

    if not name:
        selecting_own_name.add(message.from_user.id)
        return await message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())

    _t_role = await active_role(message.from_user.id)
    await loading_answer(
        message, "⏳ Загружаю твой график...",
        get_day_schedule(name, now_local().day, target_role=_t_role),
        reply_markup=my_schedule_kb()
    )

@dp.message(F.text == "📆 Завтра")
async def tomorrow(message: Message):
    name = await active_name(message.from_user.id)

    if not name:
        selecting_own_name.add(message.from_user.id)
        return await message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())

    _tm_role = await active_role(message.from_user.id)
    tomorrow_dt = now_local() + timedelta(days=1)
    await loading_answer(
        message, "⏳ Загружаю график на завтра...",
        get_day_schedule(name, tomorrow_dt.day, tomorrow_dt.month, tomorrow_dt.year, target_role=_tm_role),
        reply_markup=my_schedule_kb()
    )

async def _show_week_schedule(message: Message, week_start_dt):
    """Показать недельный график начиная с week_start_dt."""
    user_id = message.from_user.id
    name = await active_name(user_id)

    if not name:
        selecting_own_name.add(user_id)
        return await message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())

    _wk_role = await active_role(user_id)
    week_days = [week_start_dt + timedelta(days=i) for i in range(7)]
    user_week[user_id] = week_days

    loading = await message.answer("⏳ Собираю график на неделю...")
    t0 = asyncio.get_event_loop().time()

    WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    RU_MONTHS_SHORT = ["", "янв", "фев", "мар", "апр", "май", "июн",
                       "июл", "авг", "сен", "окт", "ноя", "дек"]

    first = week_days[0]
    last = week_days[-1]
    if first.month == last.month:
        header = f"🗓 Неделя: {first.day}–{last.day} {MONTHS[first.month]}"
    else:
        header = f"🗓 Неделя: {first.day} {RU_MONTHS_SHORT[first.month]} – {last.day} {RU_MONTHS_SHORT[last.month]}"

    lines = [header, ""]
    for dt in week_days:
        is_weekend = dt.weekday() in (4, 5) or (dt.month, dt.day) in RU_HOLIDAYS
        day_label = f"{WEEKDAYS_SHORT[dt.weekday()]} {dt.day}"
        if is_weekend:
            day_label += " ❗"

        try:
            row, _ = await find_row(name, dt.day, dt.month, dt.year, target_role=_wk_role)
            people_by_role = await get_people_for_day(dt.day, dt.month, dt.year)
            total_on_shift = sum(len(v) for v in people_by_role.values())
            if row:
                value = await get_day_value(row, dt.day, dt.month, dt.year)
                if is_work_shift(value):
                    lines.append(f"{day_label} — {detect_shift(value)} ✅ (на смене: {total_on_shift})")
                else:
                    lines.append(f"{day_label} — выходной 🏖 (на смене: {total_on_shift})")
            else:
                lines.append(f"{day_label} — нет данных")
        except (ValueError, ConnectionError):
            lines.append(f"{day_label} — таблица недоступна")

    elapsed = asyncio.get_event_loop().time() - t0
    if elapsed < _MIN_LOADING_SEC:
        await asyncio.sleep(_MIN_LOADING_SEC - elapsed)
    try:
        await loading.delete()
    except Exception:
        pass
    await message.answer("\n".join(lines), reply_markup=week_kb(week_days))


@dp.message(F.text == "🗓 Недели")
async def week(message: Message):
    now = now_local()
    week_start = now - timedelta(days=now.weekday())
    await _show_week_schedule(message, week_start)


@dp.message(F.text == "◀️ Пред. неделя")
async def prev_week(message: Message):
    week_days = user_week.get(message.from_user.id)
    if not week_days:
        return await message.answer("Сначала открой неделю.", reply_markup=my_schedule_kb())
    await _show_week_schedule(message, week_days[0] - timedelta(days=7))


@dp.message(F.text == "▶️ След. неделя")
async def next_week(message: Message):
    week_days = user_week.get(message.from_user.id)
    if not week_days:
        return await message.answer("Сначала открой неделю.", reply_markup=my_schedule_kb())
    await _show_week_schedule(message, week_days[0] + timedelta(days=7))


@dp.message(F.text.regexp(r"^📅 (Пн|Вт|Ср|Чт|Пт|Сб|Вс) \d+$"))
async def week_day_detail(message: Message):
    user_id = message.from_user.id
    name = await active_name(user_id)

    if not name:
        selecting_own_name.add(user_id)
        return await message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())

    week_days = user_week.get(user_id)
    if not week_days:
        return await message.answer("Сначала открой неделю.", reply_markup=my_schedule_kb())

    # Парсим "📅 Ср 4" → ищем совпадение в сохранённых днях
    parts = message.text.replace("📅 ", "").strip().split()
    day_num = int(parts[1])

    target = None
    for dt in week_days:
        if dt.day == day_num:
            target = dt
            break

    if not target:
        return await message.answer("Не нашёл этот день.", reply_markup=week_kb(week_days))

    WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    day_label = f"{WEEKDAYS_SHORT[target.weekday()]} {target.day} {MONTHS[target.month]}"
    _wd_role = await active_role(user_id)
    await loading_answer(
        message, f"⏳ Загружаю {day_label}...",
        get_day_schedule(name, target.day, target.month, target.year, target_role=_wd_role),
        reply_markup=week_kb(week_days)
    )

@dp.message(F.text == "📋 Весь график")
@dp.message(F.text == "📋 Выбрать месяц")
async def choose_month(message: Message):
    await message.answer("Выбери месяц:", reply_markup=months_kb())

@dp.message(F.text.regexp(r"^📋 \w+ \d{4}$"))
async def full_schedule(message: Message):
    name = await active_name(message.from_user.id)

    if not name:
        selecting_own_name.add(message.from_user.id)
        return await message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())

    # Парсим "📋 Май 2026" → month=5, year=2026
    parts = message.text.replace("📋 ", "").strip().split()
    month_name = parts[0]
    year = int(parts[1])
    month = MONTHS_NOM.index(month_name)

    if month == 0:
        return await message.answer("Не могу определить месяц.", reply_markup=my_schedule_kb())

    _fs_role = await active_role(message.from_user.id)
    max_day = calendar.monthrange(year, month)[1]
    await loading_answer(
        message, "⏳ Загружаю полный график...",
        get_range_schedule(name, 1, max_day, month, year, target_role=_fs_role),
        reply_markup=my_schedule_kb()
    )

@dp.message(F.text == "👥 Кто сегодня")
async def who_today(message: Message):
    await loading_answer(
        message, "⏳ Проверяю, кто работает сегодня...",
        get_people(now_local().day, message.from_user.id),
        reply_markup=today_tomorrow_kb()
    )

@dp.message(F.text == "👥 Кто завтра")
async def who_tomorrow(message: Message):
    tomorrow_dt = now_local() + timedelta(days=1)
    await loading_answer(
        message, "⏳ Проверяю, кто работает завтра...",
        get_people(tomorrow_dt.day, message.from_user.id, tomorrow_dt.month, tomorrow_dt.year),
        reply_markup=today_tomorrow_kb()
    )

@dp.message(F.text == "🔔 Уведомления")
@with_loading("⏳ Загружаю...")
async def notifications_menu(message: Message):
    user_id = message.from_user.id

    if user_id in viewing_colleague:
        return await message.answer(
            "Уведомления можно настраивать только для своего имени.\nНажми «⬅️ Вернуться к себе».",
            reply_markup=colleague_kb()
        )

    user = await get_user(user_id)

    if not user or not user[1]:
        selecting_own_name.add(user_id)
        return await message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())

    status = "включены 🔔" if user[2] else "выключены 🔕"
    notify_time = user[3] or "не задано"

    await message.answer(
        f"🔔 Настройки уведомлений\n\nСтатус: {status}\nВремя: {notify_time}",
        reply_markup=notifications_kb()
    )

@dp.message(F.text == "🔔 Включить")
@with_loading("⏳ Сохраняю...")
async def notifications_on(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)

    if not user or not user[1]:
        selecting_own_name.add(user_id)
        return await message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())

    if not user[3]:
        waiting_for_time.add(user_id)
        return await message.answer("Сначала задай время уведомления. Например: 09:30")

    await save_user(user_id, notify=1)

    await message.answer(
        f"Уведомления включены 🔔\nВремя: {user[3]}",
        reply_markup=await main_kb_async(user_id)
    )

@dp.message(F.text == "🔕 Выключить")
@with_loading("⏳ Сохраняю...")
async def notifications_off(message: Message):
    await save_user(message.from_user.id, notify=0)
    waiting_for_time.discard(message.from_user.id)

    await message.answer("Уведомления выключены 🔕", reply_markup=await main_kb_async(message.from_user.id))

@dp.message(F.text == "✍️ Задать время")
@with_loading("⏳ Загружаю...")
async def ask_notification_time(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)

    if not user or not user[1]:
        selecting_own_name.add(user_id)
        return await message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())

    waiting_for_time.add(user_id)

    await message.answer("Напиши время уведомления в формате ЧЧ:ММ\n\nНапример: 09:30")

# ── Зарплата ───────────────────────────────────────────────────────────────

# Состояния для флоу внесения смены
shift_history_selected_period = {}  # user_id -> (year, month, start_day, end_day)
shift_history_selected_month = {}  # user_id -> (year, month)
salary_mode: set[int] = set()
shift_entering: dict[int, dict] = {}
waiting_shift_hours: set[int] = set()
_salary_period_data: dict[int, tuple] = {}  # {user_id: (year, month, start, end)}


def get_role_key(role: str | None) -> str | None:
    if not role:
        return None
    parts = role.split(" ", 1)
    return parts[1] if len(parts) == 2 else role


@dp.message(F.text == "💰 Зарплата")
@with_loading("⏳ Загружаю...")
async def salary_menu(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    if not user or not user[1]:
        return await message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())
    track_hours = user[5] if user and len(user) > 5 else 0
    salary_mode.add(user_id)
    role = user[4] if user and len(user) > 4 else None
    role_line = f"\n{DEPT_EMOJIS.get(role, role)}" if role else ""
    await message.answer(f"💰 Зарплата\n{user[1]}{role_line}", reply_markup=salary_kb(track_hours or 0))


@dp.message(F.text == "📊 Примерная зарплата")
@with_loading("⏳ Загружаю...")
async def salary_stats_choose_period(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    if not user or not user[1]:
        return await message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())
    await message.answer("Выбери период:", reply_markup=salary_period_kb())


async def show_salary_stats(message: Message, year: int, month: int, period_start: int, period_end: int):
    user_id = message.from_user.id
    user = await get_user(user_id)
    name = user[1]
    role = user[4] if len(user) > 4 else None
    track_hours = user[5] if len(user) > 5 else 0

    period_name = str(period_start) + "-" + str(period_end)
    month_name = MONTHS_NOM[month] + " " + str(year) + " (" + period_name + ")"

    schedule_shifts = 0
    schedule_hours = 0.0
    no_data = True

    for day in range(period_start, period_end + 1):
        try:
            row, _ = await find_row(name, day, month, year, target_role=role)
            if row:
                no_data = False
                value = await get_day_value(row, day, month, year)
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

    await message.answer("\n".join(lines), reply_markup=salary_kb(track_hours or 0))


@dp.message(F.text == "📅 Текущий период")
async def salary_current_period(message: Message):
    now = now_local()
    month, year = now.month, now.year
    if now.day <= 15:
        period_start, period_end = 1, 15
    else:
        period_end = calendar.monthrange(year, month)[1]
        period_start = 16
    await show_salary_stats(message, year, month, period_start, period_end)


@dp.message(F.text.regexp(r"^(1-15|16-\d+) [А-Яа-я]+$"))
async def salary_period_selected(message: Message):
    text = message.text.strip()
    now = now_local()

    # Парсим период и месяц из текста кнопки
    parts = text.split(" ", 1)
    period_part = parts[0]
    month_word = parts[1] if len(parts) > 1 else ""

    # Находим месяц
    month_num = None
    for num, name in MONTHS_RU.items():
        if name == month_word:
            month_num = num
            break

    if not month_num:
        return await message.answer("Не удалось определить период.", reply_markup=salary_period_kb())

    # Определяем год
    if month_num > now.month:
        year = now.year - 1
    else:
        year = now.year

    # Определяем start/end
    if period_part == "1-15":
        period_start, period_end = 1, 15
    else:
        period_start = 16
        period_end = calendar.monthrange(year, month_num)[1]

    await show_salary_stats(message, year, month_num, period_start, period_end)


@dp.message(F.text == "⚙️ Настройки учёта")
@with_loading("⏳ Загружаю...")
async def salary_settings(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    track_hours = user[5] if user and len(user) > 5 else 0
    notify_hours = user[6] if user and len(user) > 6 else 0
    notify_info = ""
    if notify_hours:
        notify_info = (
            "\n\n🕐 Расписание уведомлений:\n"
            "  Утро (Пн–Чт, Вс) → 23:05\n"
            "  Утро (Пт, Сб) → 01:05 (след. день)\n"
            "  Вечер (Пн–Чт, Вс) → 02:05 (след. день)\n"
            "  Вечер (Пт, Сб) → 04:05 (след. день)"
        )
    await message.answer(
        "⚙️ Настройки учёта часов:" + notify_info,
        reply_markup=salary_settings_kb(track_hours or 0, notify_hours or 0)
    )


@dp.message(F.text.in_({"⬜ Включить учёт часов", "🔴 Выключить учёт часов"}))
@with_loading("⏳ Сохраняю...")
async def toggle_track_hours(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    track_hours = user[5] if user and len(user) > 5 else 0
    notify_hours = user[6] if user and len(user) > 6 else 0
    new_val = 0 if track_hours else 1
    await save_user(user_id, track_hours=new_val)
    text = "✅ Учёт часов включён! Теперь можешь вносить смены." if new_val else "⬜ Учёт часов выключен."
    await message.answer(text, reply_markup=salary_settings_kb(new_val, notify_hours or 0))


@dp.message(F.text.in_({"🔔 Уведомление включено", "🔕 Уведомление выключено"}))
@with_loading("⏳ Сохраняю...")
async def toggle_notify_hours(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    track_hours = user[5] if user and len(user) > 5 else 0
    notify_hours = user[6] if user and len(user) > 6 else 0
    new_val = 0 if notify_hours else 1
    await save_user(user_id, notify_hours=new_val)
    if new_val:
        schedule_text = (
            "🔔 Уведомление включено.\n\n"
            "Буду напоминать внести часы автоматически:\n"
            "• Утро (Пн–Чт, Вс) — в 23:05\n"
            "• Утро (Пт, Сб) — в 01:05 (след. день)\n"
            "• Вечер (Пн–Чт, Вс) — в 02:05 (след. день)\n"
            "• Вечер (Пт, Сб) — в 04:05 (след. день)"
        )
        await message.answer(schedule_text, reply_markup=salary_settings_kb(track_hours or 0, new_val))
    else:
        await message.answer("🔕 Уведомление выключено.", reply_markup=salary_settings_kb(track_hours or 0, new_val))


# ask_hours_notify_time удалён — кнопка 🕐 не показывалась пользователю


@dp.message(F.text == "🗑 Удалить смену из истории")
@with_loading("⏳ Загружаю...")
async def delete_shift_choose(message: Message):
    user_id = message.from_user.id
    now = now_local()
    shifts = await get_shifts_for_month(user_id, now.year, now.month)
    if not shifts:
        user = await get_user(user_id)
        track_hours = user[5] if user and len(user) > 5 else 0
        notify_hours = user[6] if user and len(user) > 6 else 0
        return await message.answer(
            "Нет внесённых смен за этот месяц.",
            reply_markup=salary_settings_kb(track_hours or 0, notify_hours or 0)
        )
    keyboard = []
    for row in shifts:
        date, hours, shift_type, is_standard, note = row
        shift_label = {"morning": "утро", "evening": "вечер"}.get(shift_type or "", "")
        keyboard.append([KeyboardButton(text="🗑 " + str(date) + " — " + str(hours) + " ч " + shift_label)])
    keyboard.append([KeyboardButton(text="⬅️ Назад к настройкам")])
    await message.answer(
        "Выбери смену для удаления:",
        reply_markup=ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
    )


@dp.message(F.text.regexp(r"^🗑 \d{4}-\d{2}-\d{2}"))
@with_loading("⏳ Удаляю...")
async def delete_shift_confirm(message: Message):
    user_id = message.from_user.id
    date_str = message.text.replace("🗑 ", "").split(" — ")[0].strip()
    deleted = await delete_shift(user_id, date_str)
    user = await get_user(user_id)
    track_hours = user[5] if user and len(user) > 5 else 0
    notify_hours = user[6] if user and len(user) > 6 else 0
    if deleted:
        await message.answer(
            "✅ Смена за " + date_str + " удалена.",
            reply_markup=salary_settings_kb(track_hours or 0, notify_hours or 0)
        )
    else:
        await message.answer(
            "Смена не найдена.",
            reply_markup=salary_settings_kb(track_hours or 0, notify_hours or 0)
        )


@dp.message(F.text == "⬅️ Назад к настройкам")
@with_loading("⏳ Загружаю...")
async def back_to_settings(message: Message):
    user_id = message.from_user.id
    shift_entering.pop(user_id, None)
    waiting_shift_hours.discard(user_id)
    user = await get_user(user_id)
    track_hours = user[5] if user and len(user) > 5 else 0
    notify_hours = user[6] if user and len(user) > 6 else 0
    await message.answer(
        "⚙️ Настройки учёта часов:",
        reply_markup=salary_settings_kb(track_hours or 0, notify_hours or 0)
    )


@dp.message(F.text == "⬅️ Назад к зарплате")
@with_loading("⏳ Загружаю...")
async def back_to_salary(message: Message):
    user_id = message.from_user.id
    shift_entering.pop(user_id, None)
    waiting_shift_hours.discard(user_id)
    user = await get_user(user_id)
    track_hours = user[5] if user and len(user) > 5 else 0
    await message.answer("💰 Зарплата", reply_markup=salary_kb(track_hours or 0))


@dp.message(F.text == "⏱ Внести смену")
async def enter_shift_start(message: Message):
    now = now_local()
    await message.answer(
        "Выбери дату смены:",
        reply_markup=await SimpleCalendar(cancel_btn="Отмена", today_btn="Сегодня").start_calendar(year=now.year, month=now.month)
    )


@dp.callback_query(SimpleCalendarCallback.filter())
@with_loading("⏳ Проверяю график...")
async def process_calendar(callback: CallbackQuery, callback_data: SimpleCalendarCallback):
    user_id = callback.from_user.id
    user = await get_user(user_id)

    selected, dt = await SimpleCalendar(cancel_btn="Отмена", today_btn="Сегодня").process_selection(callback, callback_data)
    if not selected:
        return

    if not user or not user[1]:
        await callback.message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())
        return

    name = user[1]
    _cal_role = user[4] if len(user) > 4 else None
    date_str = dt.strftime("%Y-%m-%d")
    existing = await get_shift_for_date(user_id, date_str)
    shift_type = None
    standard_hours = None

    try:
        row, _ = await find_row(name, dt.day, dt.month, dt.year, target_role=_cal_role)
        if row:
            value = await get_day_value(row, dt.day, dt.month, dt.year)
            if is_work_shift(value):
                shift_type = detect_shift_type(value)
                standard_hours = get_standard_hours(shift_type, dt)
    except (ValueError, ConnectionError):
        pass

    shift_entering[user_id] = {
        "date": date_str,
        "shift_type": shift_type,
        "standard_hours": standard_hours,
    }

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

    await callback.message.answer("\n".join(lines), reply_markup=shift_hours_kb(standard_hours))


@dp.message(F.text.in_({"📥 Сегодня", "📥 Вчера"}))
@with_loading("⏳ Проверяю график...")
async def shift_date_selected(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    if not user or not user[1]:
        return await message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())
    name = user[1]
    _sd_role = user[4] if len(user) > 4 else None
    now = now_local()
    dt = now if message.text == "📥 Сегодня" else now - timedelta(days=1)
    date_str = dt.strftime("%Y-%m-%d")
    existing = await get_shift_for_date(user_id, date_str)
    shift_type = None
    standard_hours = None
    try:
        row, _ = await find_row(name, dt.day, dt.month, dt.year, target_role=_sd_role)
        if row:
            value = await get_day_value(row, dt.day, dt.month, dt.year)
            if is_work_shift(value):
                shift_type = detect_shift_type(value)
                standard_hours = get_standard_hours(shift_type, dt)
    except (ValueError, ConnectionError):
        pass
    shift_entering[user_id] = {
        "date": date_str,
        "shift_type": shift_type,
        "standard_hours": standard_hours,
    }
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
    await message.answer("\n".join(lines), reply_markup=shift_hours_kb(standard_hours))


@dp.message(F.text.startswith("✅ Стандартная ("))
@with_loading("⏳ Сохраняю...")
async def shift_standard_selected(message: Message):
    user_id = message.from_user.id
    state = shift_entering.get(user_id)
    if not state:
        return await message.answer("Сначала выбери дату.", reply_markup=shift_date_kb())
    await save_shift(
        user_id=user_id,
        date=state["date"],
        hours=state["standard_hours"],
        shift_type=state.get("shift_type"),
        is_standard=True,
    )
    shift_entering.pop(user_id, None)
    user = await get_user(user_id)
    track_hours = user[5] if user and len(user) > 5 else 0
    await message.answer(
        "✅ Смена внесена: " + fmt_hours(state["standard_hours"]) + " ч за " + state["date"],
        reply_markup=salary_kb(track_hours or 0)
    )


@dp.message(F.text == "✍️ Указать своё время")
async def shift_custom_hours(message: Message):
    user_id = message.from_user.id
    if user_id not in shift_entering:
        return await message.answer("Сначала выбери дату.", reply_markup=shift_date_kb())
    waiting_shift_hours.add(user_id)
    await message.answer("Напиши количество часов, например: 11.5")



def _month_label(month: int) -> str:
    try:
        return MONTHS_NOM[month]
    except Exception:
        try:
            return MONTHS[month]
        except Exception:
            return str(month)


def get_shift_history_months():
    """
    Месяцы для истории смен на основе SHEET_GID_MAP.

    Показываем текущий и будущие месяцы, для которых есть хотя бы один gid.
    Как только добавишь gid июля, июль появится в списке.
    """
    today = now_local().date()
    months = set()

    for key in SHEET_GID_MAP.keys():
        if not isinstance(key, tuple) or len(key) != 3:
            continue

        year, month, _start_day = key

        # Оставляем текущий и будущие месяцы.
        if (year, month) >= (today.year, today.month):
            months.add((year, month))

    return sorted(months)


def shift_history_month_kb():
    """Клавиатура выбора месяца истории смен."""
    buttons = []

    for year, month in get_shift_history_months():
        buttons.append([KeyboardButton(text=f"🧾 Месяц: {_month_label(month)} {year}")])

    buttons.append([KeyboardButton(text="⬅️ Назад к зарплате")])
    buttons.append([KeyboardButton(text="🏠 Главное меню")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def _parse_shift_history_month_button(text: str):
    """
    Парсит кнопку:
    📅 Июнь 2026
    """
    m = re.match(r"^🧾 Месяц: (.+) (\d{4})$", text.strip())
    if not m:
        return None

    month_label = m.group(1).strip()
    year = int(m.group(2))

    for month in range(1, 13):
        names = set()
        try:
            names.add(str(MONTHS[month]))
        except Exception:
            pass
        try:
            names.add(str(MONTHS_NOM[month]))
        except Exception:
            pass

        if month_label in names:
            return year, month

    return None


def shift_history_period_kb(month=None, year=None):
    """Клавиатура выбора периода истории смен."""
    now = now_local()
    month = month or now.month
    year = year or now.year

    last_day = calendar.monthrange(year, month)[1]
    month_name = _month_label(month)

    keyboard = [
        [KeyboardButton(text=f"🧾 Период: 1–15 {month_name} {year}")],
        [KeyboardButton(text=f"🧾 Период: 16–{last_day} {month_name} {year}")],
        [KeyboardButton(text="⬅️ Назад к выбору месяца")],
        [KeyboardButton(text="⬅️ Назад к зарплате")],
        [KeyboardButton(text="🏠 Главное меню")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def _parse_shift_history_period_button(text: str):
    """
    Парсит кнопку:
    📋 1–15 Июнь 2026
    📋 16–30 Июнь 2026
    """
    m = re.match(r"^🧾 Период: (\d+)–(\d+) (.+) (\d{4})$", text.strip())
    if not m:
        return None

    start_day = int(m.group(1))
    end_day = int(m.group(2))
    month_label = m.group(3).strip()
    year = int(m.group(4))

    month = None
    for idx in range(1, 13):
        names = set()
        try:
            names.add(str(MONTHS[idx]))
        except Exception:
            pass
        try:
            names.add(str(MONTHS_NOM[idx]))
        except Exception:
            pass

        if month_label in names:
            month = idx
            break

    if month is None:
        return None

    return year, month, start_day, end_day



def shift_history_actions_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🗑 Удалить смену из этого периода")],
            [KeyboardButton(text="⬅️ Назад к выбору периода")],
            [KeyboardButton(text="💰 Зарплата")],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True
    )


def shift_history_delete_kb(shifts):
    keyboard = []

    for date_str, hours, shift_type, is_standard, note in shifts:
        shift_label = ""
        if shift_type == "morning":
            shift_label = "утро"
        elif shift_type == "evening":
            shift_label = "вечер"
        elif shift_type:
            shift_label = str(shift_type)

        label = f"❌ {date_str} — {fmt_hours(hours)} ч"
        if shift_label:
            label += f" {shift_label}"

        keyboard.append([KeyboardButton(text=label)])

    keyboard.append([KeyboardButton(text="⬅️ Назад к истории")])
    keyboard.append([KeyboardButton(text="💰 Зарплата")])
    keyboard.append([KeyboardButton(text="🏠 Главное меню")])

    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


async def get_shift_history_period_shifts(user_id: int, year: int, month: int, start_day: int, end_day: int):
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



async def build_shift_history_text(user_id: int, year: int, month: int, start_day: int, end_day: int) -> str:
    """Текст истории смен за выбранный период."""
    period_shifts = await get_shift_history_period_shifts(user_id, year, month, start_day, end_day)

    month_name = _month_label(month)
    lines = [f"📋 История смен: {start_day}–{end_day} {month_name} {year}", ""]

    if not period_shifts:
        lines.append("За этот период смены не внесены.")
        return "\n".join(lines)

    total_hours = 0

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




@dp.message(F.text == "📋 История смен")
async def shift_history(message: Message):
    months = get_shift_history_months()
    if not months:
        return await message.answer(
            "📋 Нет доступных месяцев для истории смен. Добавь gid в SHEET_GID_MAP.",
            reply_markup=salary_kb()
        )

    await message.answer(
        "📅 Выбери месяц истории смен:",
        reply_markup=shift_history_month_kb()
    )


@dp.message(F.text.regexp(r"^🧾 Месяц: .+ \d{4}$"))
async def shift_history_month_selected(message: Message):
    parsed = _parse_shift_history_month_button(message.text)
    if not parsed:
        return

    year, month = parsed
    shift_history_selected_month[message.from_user.id] = (year, month)

    await message.answer(
        "📋 Выбери период истории смен:",
        reply_markup=shift_history_period_kb(month, year)
    )


@dp.message(F.text == "⬅️ Назад к выбору месяца")
async def shift_history_back_to_month(message: Message):
    await message.answer(
        "📅 Выбери месяц истории смен:",
        reply_markup=shift_history_month_kb()
    )



@dp.message(F.text == "⬅️ Назад к выбору периода")
async def shift_history_back_to_period(message: Message):
    user_id = message.from_user.id

    selected_month = shift_history_selected_month.get(user_id)

    if not selected_month:
        period = shift_history_selected_period.get(user_id)
        if period:
            year, month, _start_day, _end_day = period
            selected_month = (year, month)

    if not selected_month:
        return await message.answer(
            "📅 Выбери месяц истории смен:",
            reply_markup=shift_history_month_kb()
        )

    year, month = selected_month
    await message.answer(
        "📋 Выбери период истории смен:",
        reply_markup=shift_history_period_kb(month, year)
    )


@dp.message(F.text.regexp(r"^🧾 Период: \d+–\d+ .+ \d{4}$"))
async def shift_history_period_selected(message: Message):
    parsed = _parse_shift_history_period_button(message.text)
    if not parsed:
        return

    year, month, start_day, end_day = parsed
    user_id = message.from_user.id

    shift_history_selected_month[user_id] = (year, month)
    shift_history_selected_period[user_id] = (year, month, start_day, end_day)
    text = await build_shift_history_text(user_id, year, month, start_day, end_day)
    await message.answer(text, reply_markup=shift_history_actions_kb())



@dp.message(F.text == "🗑 Удалить смену из этого периода")
async def shift_history_delete_choose(message: Message):
    user_id = message.from_user.id
    period = shift_history_selected_period.get(user_id)

    if not period:
        return await message.answer(
            "Сначала выбери период истории смен.",
            reply_markup=shift_history_month_kb()
        )

    year, month, start_day, end_day = period
    shifts = await get_shift_history_period_shifts(user_id, year, month, start_day, end_day)

    if not shifts:
        return await message.answer(
            "В этом периоде нет внесённых смен.",
            reply_markup=shift_history_actions_kb()
        )

    await message.answer(
        "🗑 Выбери смену для удаления:",
        reply_markup=shift_history_delete_kb(shifts)
    )


@dp.message(F.text == "⬅️ Назад к истории")
async def shift_history_back_to_selected_period(message: Message):
    user_id = message.from_user.id
    period = shift_history_selected_period.get(user_id)

    if not period:
        return await message.answer(
            "📅 Выбери месяц истории смен:",
            reply_markup=shift_history_month_kb()
        )

    year, month, start_day, end_day = period
    text = await build_shift_history_text(user_id, year, month, start_day, end_day)
    await message.answer(text, reply_markup=shift_history_actions_kb())


@dp.message(F.text.regexp(r"^❌ \d{4}-\d{2}-\d{2} — .+"))
async def shift_history_delete_confirm(message: Message):
    user_id = message.from_user.id

    m = re.match(r"^❌ (\d{4}-\d{2}-\d{2}) — .+", message.text)
    if not m:
        return

    date_str = m.group(1)
    deleted = await delete_shift(user_id, date_str)

    if deleted:
        await message.answer(f"✅ Смена {date_str} удалена.")
    else:
        await message.answer(f"⚠️ Смена {date_str} не найдена или уже удалена.")

    period = shift_history_selected_period.get(user_id)
    if period:
        year, month, start_day, end_day = period
        text = await build_shift_history_text(user_id, year, month, start_day, end_day)
        await message.answer(text, reply_markup=shift_history_actions_kb())
    else:
        await message.answer("📋 История смен", reply_markup=shift_history_month_kb())


@dp.message()
@with_loading("⏳ Обрабатываю...")
async def text_handler(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()

    if user_id in waiting_for_time:
        if not is_valid_time(text):
            return await message.answer("Неверный формат. Напиши так: 09:30")

        await save_user(user_id, notify_time=text, notify=1)
        waiting_for_time.discard(user_id)

        return await message.answer(
            "Время уведомлений сохранено: " + text + "\nУведомления включены 🔔",
            reply_markup=await main_kb_async(user_id)
        )

    if user_id in waiting_shift_hours:
        try:
            hours = float(text.replace(",", "."))
            if hours <= 0 or hours > 24:
                raise ValueError
        except ValueError:
            return await message.answer("Напиши число, например: 11.5")
        state = shift_entering.get(user_id)
        if not state:
            waiting_shift_hours.discard(user_id)
            return await message.answer("Что-то пошло не так. Начни заново.", reply_markup=shift_date_kb())
        await save_shift(
            user_id=user_id,
            date=state["date"],
            hours=hours,
            shift_type=state.get("shift_type"),
            is_standard=False,
        )
        waiting_shift_hours.discard(user_id)
        shift_entering.pop(user_id, None)
        user = await get_user(user_id)
        track_hours = user[5] if user and len(user) > 5 else 0
        return await message.answer(
            "✅ Смена внесена: " + fmt_hours(hours) + " ч за " + state["date"],
            reply_markup=salary_kb(track_hours or 0)
        )

    await message.answer("Используй кнопки ниже.", reply_markup=await main_kb_async(user_id))


@dp.errors()
async def global_error_handler(event) -> bool:
    # event — объект ErrorEvent в aiogram 3
    exception = event.exception
    logging.error("Необработанная ошибка: %s\n%s", exception, traceback.format_exc())
    try:
        update = event.update
        msg = None
        if update.message:
            msg = update.message
        elif update.callback_query:
            msg = update.callback_query.message
        if msg:
            await msg.answer("⚠️ Что-то пошло не так. Попробуй ещё раз или вернись в главное меню.")
    except Exception:
        pass
    return True


async def main():
    if not BOT_TOKEN:
        print("Ошибка: BOT_TOKEN не найден в .env")
        return

    bot = Bot(token=BOT_TOKEN)

    await load_full_sheet()

    _notification_task = asyncio.create_task(notification_loop(bot))
    _notification_task.add_done_callback(
        lambda t: logging.exception(
            "notification_loop: фоновая задача завершилась с ошибкой",
            exc_info=t.exception(),
        ) if not t.cancelled() and t.exception() else None
    )
    _hours_notification_task = asyncio.create_task(hours_notification_loop(bot))
    _hours_notification_task.add_done_callback(
        lambda t: logging.exception(
            "hours_notification_loop: фоновая задача завершилась с ошибкой",
            exc_info=t.exception(),
        ) if not t.cancelled() and t.exception() else None
    )

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
