import asyncio
import os
import re
import calendar
import logging
import traceback
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message


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
    SHIFT_HOURS,
    SHIFT_END_NOTIFY,
    SHEET_GID_MAP,
)

from keyboards import (
    configure_keyboard_context,
    get_available_periods,
    compare_period_kb,
    compare_kb,
    week_kb,
    main_kb,
    main_kb_async,
    my_schedule_kb,
    months_kb,
    today_tomorrow_kb,
    colleague_kb,
    dep_kb,
    own_names_kb,
    colleague_names_kb,
    compare_names_kb,
    notifications_kb,
)

from ui_utils import (
    configure_ui_utils,
    with_loading,
    loading_answer,
    is_valid_time,
    month_label,
    MIN_LOADING_SEC,
)

from departments_manager import (
    configure_departments_manager,
    DEPARTMENTS,
    ALL_NAMES,
    DEPT_EMOJIS,
    SHEET_ROLES,
    refresh_departments,
    is_department_label,
    is_person_name,
    role_display_label,
    ordered_role_keys,
    roles_for_person,
    person_has_ambiguous_role,
    normalize_role_name,
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

from repositories.shifts_repo import get_shift_for_date

from routers.colleagues import router as colleagues_router
from routers.fallback import router as fallback_router
from routers.salary import router as salary_router
from services.compare_service import configure_compare_service
from services.salary_service import configure_salary_service
from fsm_context import (
    active_name,
    active_role,
    clear_colleague_view,
    clear_notification_state,
    get_compare_selected,
    get_viewing_colleague,
    pop_last_selected_dept,
    prompt_choose_own_name,
    reset_compare_mode,
    reset_modes,
    set_last_selected_dept,
    set_user_week,
    get_user_week,
)

from states import (
    NotificationStates,
    NameFlowStates,
    CompareStates,
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

dp = Dispatcher(storage=MemoryStorage())




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

configure_departments_manager(_clean_person_name_value, load_sheet)

SCHEDULE_MAX_DAY_COL = 16  # B:P, правая часть листа содержит статистику, не график

ROLES = SHEET_ROLES

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
configure_ui_utils(MONTHS, MONTHS_NOM)

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



def get_day_column(df, day):
    for i in range(len(df)):
        first = str(df.iloc[i, 0]).strip()

        if first in ROLES:
            row = df.iloc[i].fillna("").astype(str).tolist()

            for col_index, value in enumerate(row[:SCHEDULE_MAX_DAY_COL + 1]):
                if str(value).strip() == str(day):
                    return col_index

    return None





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


configure_salary_service(find_row=find_row, get_day_value=get_day_value)
configure_compare_service(find_row=find_row, get_day_value=get_day_value)


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
            f"{start_day}–{end_day} {month_label(month)} {year}: gid={gid} ({status})"
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
async def start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await reset_modes(user_id, state)

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
        await state.set_state(NameFlowStates.choosing_own_department)

@dp.message(F.text == "🏠 Главное меню")
@with_loading("⏳ Загружаю...")
async def home(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await reset_modes(user_id, state)

    name = await get_user_name(user_id)
    greeting = f"Привет, {name} 👋" if name else "🏠 Главное меню"
    await message.answer(greeting, reply_markup=await main_kb_async(user_id))

@dp.message(F.text == "📌 Мой график")
async def my_schedule_menu(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await clear_colleague_view(state)
    await reset_compare_mode(state)

    name = await active_name(user_id, state)
    loading = await message.answer("⏳ Загружаю твой график...")
    t0 = asyncio.get_event_loop().time()

    _ms_role = await active_role(user_id, state)
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
    if elapsed < MIN_LOADING_SEC:
        await asyncio.sleep(MIN_LOADING_SEC - elapsed)
    try:
        await loading.delete()
    except Exception:
        pass
    await message.answer(f"📌 Мой график{today_line}", reply_markup=my_schedule_kb())

@dp.message(F.text == "📆 График сегодня/завтра")
async def today_tomorrow_menu(message: Message):
    await message.answer("📆 График сегодня/завтра:", reply_markup=today_tomorrow_kb())


@dp.message(F.text.startswith("👤 "))
async def choose_own_name(message: Message, state: FSMContext):
    await clear_notification_state(state)
    await clear_colleague_view(state)
    await reset_compare_mode(state)
    await state.set_state(NameFlowStates.choosing_own_department)
    await message.answer("Выбери своё подразделение:", reply_markup=dep_kb())


@dp.message(F.text.func(is_department_label))
async def department_selected(message: Message, state: FSMContext):
    user_id = message.from_user.id
    department = message.text

    parts = department.split(" ", 1)
    dept_role = parts[1] if len(parts) == 2 else department
    await set_last_selected_dept(state, dept_role)

    current = await state.get_state()
    if current == NameFlowStates.choosing_compare_department.state:
        await state.set_state(CompareStates.selecting_people)
        await message.answer(
            "Выбери сотрудника для сравнения:",
            reply_markup=await compare_names_kb(
                department, user_id, await get_compare_selected(state),
            ),
        )
    elif current == NameFlowStates.choosing_colleague_department.state:
        await state.set_state(None)
        await message.answer("Выбери коллегу:", reply_markup=await colleague_names_kb(department, user_id))
    else:
        await state.set_state(NameFlowStates.choosing_own_name)
        await message.answer("Выбери своё имя:", reply_markup=own_names_kb(department))


@dp.message(F.text.func(is_person_name))
@with_loading("⏳ Сохраняю...")
async def own_name_selected(message: Message, state: FSMContext):
    user_id = message.from_user.id

    user_role = await pop_last_selected_dept(state)
    if not user_role:
        for dept_label, names in DEPARTMENTS.items():
            if message.text in names:
                parts = dept_label.split(" ", 1)
                user_role = parts[1] if len(parts) == 2 else dept_label
                break

    await save_user(user_id, name=message.text, notify=0, notify_time='', role=user_role)
    await reset_modes(user_id, state)

    await message.answer(
        f"✅ Готово! Теперь ты — {message.text}",
        reply_markup=await main_kb_async(user_id),
    )


@dp.message(F.text == "📅 Сегодня")
async def today(message: Message, state: FSMContext):
    name = await active_name(message.from_user.id, state)

    if not name:
        return await prompt_choose_own_name(message, state)

    _t_role = await active_role(message.from_user.id, state)
    await loading_answer(
        message, "⏳ Загружаю твой график...",
        get_day_schedule(name, now_local().day, target_role=_t_role),
        reply_markup=my_schedule_kb()
    )

@dp.message(F.text == "📆 Завтра")
async def tomorrow(message: Message, state: FSMContext):
    name = await active_name(message.from_user.id, state)

    if not name:
        return await prompt_choose_own_name(message, state)

    _tm_role = await active_role(message.from_user.id, state)
    tomorrow_dt = now_local() + timedelta(days=1)
    await loading_answer(
        message, "⏳ Загружаю график на завтра...",
        get_day_schedule(name, tomorrow_dt.day, tomorrow_dt.month, tomorrow_dt.year, target_role=_tm_role),
        reply_markup=my_schedule_kb()
    )

async def _show_week_schedule(message: Message, week_start_dt, state: FSMContext):
    """Показать недельный график начиная с week_start_dt."""
    user_id = message.from_user.id
    name = await active_name(user_id, state)

    if not name:
        return await prompt_choose_own_name(message, state)

    _wk_role = await active_role(user_id, state)
    week_days = [week_start_dt + timedelta(days=i) for i in range(7)]
    await set_user_week(state, week_days)

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
    if elapsed < MIN_LOADING_SEC:
        await asyncio.sleep(MIN_LOADING_SEC - elapsed)
    try:
        await loading.delete()
    except Exception:
        pass
    await message.answer("\n".join(lines), reply_markup=week_kb(week_days))


@dp.message(F.text == "🗓 Недели")
async def week(message: Message, state: FSMContext):
    now = now_local()
    week_start = now - timedelta(days=now.weekday())
    await _show_week_schedule(message, week_start, state)


@dp.message(F.text == "◀️ Пред. неделя")
async def prev_week(message: Message, state: FSMContext):
    week_days = await get_user_week(state)
    if not week_days:
        return await message.answer("Сначала открой неделю.", reply_markup=my_schedule_kb())
    await _show_week_schedule(message, week_days[0] - timedelta(days=7), state)


@dp.message(F.text == "▶️ След. неделя")
async def next_week(message: Message, state: FSMContext):
    week_days = await get_user_week(state)
    if not week_days:
        return await message.answer("Сначала открой неделю.", reply_markup=my_schedule_kb())
    await _show_week_schedule(message, week_days[0] + timedelta(days=7), state)


@dp.message(F.text.regexp(r"^📅 (Пн|Вт|Ср|Чт|Пт|Сб|Вс) \d+$"))
async def week_day_detail(message: Message, state: FSMContext):
    user_id = message.from_user.id
    name = await active_name(user_id, state)

    if not name:
        return await prompt_choose_own_name(message, state)

    week_days = await get_user_week(state)
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
    _wd_role = await active_role(user_id, state)
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
async def full_schedule(message: Message, state: FSMContext):
    name = await active_name(message.from_user.id, state)

    if not name:
        return await prompt_choose_own_name(message, state)

    # Парсим "📋 Май 2026" → month=5, year=2026
    parts = message.text.replace("📋 ", "").strip().split()
    month_name = parts[0]
    year = int(parts[1])
    month = MONTHS_NOM.index(month_name)

    if month == 0:
        return await message.answer("Не могу определить месяц.", reply_markup=my_schedule_kb())

    _fs_role = await active_role(message.from_user.id, state)
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
async def notifications_menu(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if await get_viewing_colleague(state):
        return await message.answer(
            "Уведомления можно настраивать только для своего имени.\nНажми «⬅️ Вернуться к себе».",
            reply_markup=colleague_kb()
        )

    user = await get_user(user_id)

    if not user or not user[1]:
        return await prompt_choose_own_name(message, state)

    status = "включены 🔔" if user[2] else "выключены 🔕"
    notify_time = user[3] or "не задано"

    await message.answer(
        f"🔔 Настройки уведомлений\n\nСтатус: {status}\nВремя: {notify_time}",
        reply_markup=notifications_kb()
    )

@dp.message(F.text == "🔔 Включить")
@with_loading("⏳ Сохраняю...")
async def notifications_on(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user = await get_user(user_id)

    if not user or not user[1]:
        return await prompt_choose_own_name(message, state)

    if not user[3]:
        await state.set_state(NotificationStates.waiting_for_time)
        return await message.answer("Сначала задай время уведомления. Например: 09:30")

    await save_user(user_id, notify=1)

    await message.answer(
        f"Уведомления включены 🔔\nВремя: {user[3]}",
        reply_markup=await main_kb_async(user_id)
    )

@dp.message(F.text == "🔕 Выключить")
@with_loading("⏳ Сохраняю...")
async def notifications_off(message: Message, state: FSMContext):
    await save_user(message.from_user.id, notify=0)
    await clear_notification_state(state)

    await message.answer("Уведомления выключены 🔕", reply_markup=await main_kb_async(message.from_user.id))

@dp.message(F.text == "✍️ Задать время")
@with_loading("⏳ Загружаю...")
async def ask_notification_time(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user = await get_user(user_id)

    if not user or not user[1]:
        return await prompt_choose_own_name(message, state)

    await state.set_state(NotificationStates.waiting_for_time)

    await message.answer("Напиши время уведомления в формате ЧЧ:ММ\n\nНапример: 09:30")


@dp.message(NotificationStates.waiting_for_time, F.text)
async def save_notification_time(message: Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text.strip()

    if not is_valid_time(text):
        return await message.answer("Неверный формат. Напиши так: 09:30")

    await save_user(user_id, notify_time=text, notify=1)
    await state.clear()

    await message.answer(
        "Время уведомлений сохранено: " + text + "\nУведомления включены 🔔",
        reply_markup=await main_kb_async(user_id),
    )


dp.include_router(salary_router)
dp.include_router(colleagues_router)
dp.include_router(fallback_router)


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
    import asyncio
    await asyncio.to_thread(init_db)
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
