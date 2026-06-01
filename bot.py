import asyncio
import os
import sqlite3
import calendar
import logging
import traceback
from io import StringIO
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import requests
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

APP_TIMEZONE = ZoneInfo("Europe/Moscow")

def now_local():
    return datetime.now(APP_TIMEZONE)

SHEET_ID = "1bRuO870pDBf6O-kXJ1O342SmxmjZgpsiacM2aPOJm9Y"
SHEET_GID_MAP = {
    (2026, 5, 1):  "1690889478",   # Май 1-15
    (2026, 5, 16): "1467004546",   # Май 16-31
    (2026, 6, 1):  "608196188",    # Июнь 1-15
    # сюда добавляй новые листы: (год, месяц, день_начала): "gid"
}

def get_gid_for_day(day):
    now = now_local()
    return get_gid_for_day_month(day, now.month, now.year)

def get_gid_for_day_month(day, month, year):
    period_start = 1 if day <= 15 else 16
    return SHEET_GID_MAP.get((year, month, period_start))

def build_csv_url(gid):
    return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"

dp = Dispatcher()

DATABASE_URL = os.getenv("DATABASE_URL")

try:
    import psycopg2
except ImportError:
    psycopg2 = None

USE_POSTGRES = bool(DATABASE_URL)


def get_db_connection():
    if USE_POSTGRES:
        return psycopg2.connect(DATABASE_URL)

    return sqlite3.connect("users.db")


def db_placeholder():
    return "%s" if USE_POSTGRES else "?"


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        name TEXT,
        notify INTEGER DEFAULT 0,
        notify_time TEXT
    )
    """)

    conn.commit()
    cursor.close()
    conn.close()


init_db()


def save_user(user_id, name=None, notify=None, notify_time=None):
    conn = get_db_connection()
    cursor = conn.cursor()

    ph = db_placeholder()

    cursor.execute(
        f"SELECT user_id FROM users WHERE user_id={ph}",
        (user_id,)
    )

    exists = cursor.fetchone()

    if not exists:
        cursor.execute(
            f"INSERT INTO users (user_id, name, notify, notify_time) VALUES ({ph}, {ph}, {ph}, {ph})",
            (user_id, name, notify or 0, notify_time)
        )
    else:
        if name is not None:
            cursor.execute(
                f"UPDATE users SET name={ph} WHERE user_id={ph}",
                (name, user_id)
            )

        if notify is not None:
            cursor.execute(
                f"UPDATE users SET notify={ph} WHERE user_id={ph}",
                (notify, user_id)
            )

        if notify_time is not None:
            cursor.execute(
                f"UPDATE users SET notify_time={ph} WHERE user_id={ph}",
                (notify_time, user_id)
            )

    conn.commit()
    cursor.close()
    conn.close()


def get_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    ph = db_placeholder()

    cursor.execute(
        f"SELECT user_id, name, notify, notify_time FROM users WHERE user_id={ph}",
        (user_id,)
    )

    user = cursor.fetchone()

    cursor.close()
    conn.close()

    return user


def get_user_name(user_id):
    user = get_user(user_id)
    return user[1] if user and user[1] else None


def get_notify_users():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT user_id, name, notify_time FROM users WHERE notify=1 AND name IS NOT NULL AND notify_time IS NOT NULL"
    )

    users = cursor.fetchall()

    cursor.close()
    conn.close()

    return users
cached_df = {}
cached_time = {}
cache_lock = asyncio.Lock()

async def download_sheet(gid):
    def sync():
        url = build_csv_url(gid)
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            r.encoding = "utf-8"
            return pd.read_csv(StringIO(r.text), header=None)
        except requests.exceptions.Timeout:
            raise ConnectionError("⏱ Google Sheets не отвечает (таймаут). Попробуй позже.")
        except requests.exceptions.ConnectionError:
            raise ConnectionError("📡 Нет соединения с Google Sheets. Проверь интернет.")
        except requests.exceptions.HTTPError as e:
            raise ConnectionError(f"❌ Ошибка доступа к таблице: {e}. Возможно таблица закрыта.")
        except Exception as e:
            raise ConnectionError(f"❌ Не удалось загрузить график: {e}")

    return await asyncio.to_thread(sync)

async def load_sheet(day, month=None, year=None):
    global cached_df, cached_time
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year

    async with cache_lock:
        gid = get_gid_for_day_month(day, month, year)
        if gid is None:
            raise ValueError(f"Нет GID для {year}-{month}, день {day}. Добавь в SHEET_GID_MAP.")

        key = gid
        now_time = now_local()

        if key in cached_df and key in cached_time:
            if (now_time - cached_time[key]).total_seconds() < 60:
                return cached_df[key]

        df = await download_sheet(gid)
        cached_df[key] = df
        cached_time[key] = now_time
        return cached_df[key]

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

DEPARTMENTS = {
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
    ],
}

ALL_NAMES = [name for group in DEPARTMENTS.values() for name in group]
ROLES = ["Менеджер", "Официант", "Бармен", "Кальян", "Хостес"]

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

waiting_for_time = set()
selecting_own_name = set()
selecting_colleague = set()
viewing_colleague = {}

comparing_users = set()
compare_selected = {}
user_week = {}  # хранит дни текущей недели для каждого пользователя

def main_kb(user_id):
    name = get_user_name(user_id) or "Моё имя"

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📌 Мой график"), KeyboardButton(text="📆 График сегодня/завтра")],
            [KeyboardButton(text="👀 Коллеги"), KeyboardButton(text="🔔 Уведомления")],
            [KeyboardButton(text=f"👤 {name}")],
        ],
        resize_keyboard=True
    )

def week_kb(week_days):
    """Кнопки с днями недели: [Пн 2] [Вт 3] ..."""
    WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    buttons = []
    row = []
    for i, dt in enumerate(week_days):
        label = f"{WEEKDAYS_SHORT[dt.weekday()]} {dt.day}"
        row.append(KeyboardButton(text=f"📅 {label}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([KeyboardButton(text="🏠 Главное меню")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def my_schedule_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📆 Завтра")],
            [KeyboardButton(text="🗓 Неделя"), KeyboardButton(text="📋 Выбрать месяц")],
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
            [KeyboardButton(text="🗓 Неделя"), KeyboardButton(text="📋 Весь график")],
            [KeyboardButton(text="🤝 Совпадения")],
            [KeyboardButton(text="⬅️ Вернуться к себе")],
        ],
        resize_keyboard=True
    )

def compare_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить сотрудника")],
            [KeyboardButton(text="✅ Посчитать совпадения")],
            [KeyboardButton(text="🧹 Очистить выбранных")],
            [KeyboardButton(text="⬅️ Назад к коллеге")],
            [KeyboardButton(text="🏠 Главное меню")],
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

def colleague_names_kb(department, user_id):
    my_name = get_user_name(user_id)
    buttons = []

    for name in DEPARTMENTS[department]:
        if name != my_name:
            buttons.append([KeyboardButton(text=f"👀 {name}")])

    buttons.append([KeyboardButton(text="🏠 Главное меню")])

    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def compare_names_kb(department, user_id):
    my_name = get_user_name(user_id)
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

async def loading_answer(message: Message, loading_text: str, result_text: str, reply_markup=None):
    loading = await message.answer(loading_text)

    try:
        await loading.delete()
    except Exception:
        pass

    await message.answer(str(result_text), reply_markup=reply_markup)

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
    comparing_users.discard(user_id)
    compare_selected.pop(user_id, None)

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

def current_period(month=None, year=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year
    max_day = calendar.monthrange(year, month)[1]
    today = now_local().day

    # если запрашиваем текущий месяц — период зависит от сегодняшнего дня
    if month == now.month and year == now.year:
        if today <= 15:
            return 1, 15
        return 16, max_day

    # если запрашиваем будущий месяц — показываем доступный период
    # проверяем какие GID есть для этого месяца
    has_first = (year, month, 1) in SHEET_GID_MAP
    has_second = (year, month, 16) in SHEET_GID_MAP

    if has_first and has_second:
        return 1, max_day
    if has_first:
        return 1, 15
    if has_second:
        return 16, max_day
    return 1, max_day

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

    is_red = weekday_index >= 4 or (now.month, day) in RU_HOLIDAYS

    if is_red:
        return f"❗ {label}"

    return label

def format_date(day, month=None, year=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year
    weekday_index = datetime(year, month, day).weekday()
    label = WEEKDAYS[weekday_index]
    is_red = weekday_index >= 4 or (month, day) in RU_HOLIDAYS
    label = f"❗ {label}" if is_red else label
    return f"{day} {MONTHS[month]} ({label})"

def clean_value(value):
    text = str(value).strip()

    if not text:
        return ""

    if text.lower() in ["nan", "none", "выходной", "-", "—"]:
        return ""

    return text

def is_work_shift(value):
    text = clean_value(value)

    if not text:
        return False

    if text.startswith(("9", "10", "11", "12", "13", "14", "15", "16")):
        return True

    if ":" in text or "-" in text:
        return True

    return False

def detect_shift(value):
    text = clean_value(value)

    if not text:
        return "выходной"

    if text.startswith(("9", "10", "11")):
        return f"{text} — утро"

    if text.startswith(("12", "13", "14", "15", "16")):
        return f"{text} — вечер"

    return text

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

            for col_index, value in enumerate(row):
                if str(value).strip() == str(day):
                    return col_index

    return None

async def find_row(name, day, month=None, year=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year
    df = await load_sheet(day, month, year)
    role = None
    needle = str(name).strip().lower()

    for i in range(len(df)):
        first = str(df.iloc[i, 0]).strip()
        if first in ROLES:
            role = first
            continue
        row = df.iloc[i].fillna("").astype(str).tolist()
        if needle and needle in " ".join(row).lower():
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
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year
    df = await load_sheet(day, month, year)
    col = get_day_column(df, day)

    if col is None:
        return {}

    role = None
    result = {}

    for i in range(len(df)):
        first = str(df.iloc[i, 0]).strip()
        if first in ROLES:
            role = first
            result[role] = []
            continue
        row = df.iloc[i].fillna("").astype(str).tolist()
        if role and len(row) > col:
            name = clean_value(row[0])
            value = row[col]
            if name and is_work_shift(value):
                result[role].append(f"{name} — {detect_shift(value)}")

    return result


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
            result.append(person_name)

    return result

async def get_my_status_for_day(user_id, day, month=None, year=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year
    my_name = get_user_name(user_id)

    if not my_name:
        return "👤 Твоё имя не выбрано."

    if not is_day_published(day, month, year):
        return "👤 Твой график: график пока не составлен."

    row, _ = await find_row(my_name, day, month, year)
    if not row:
        return f"👤 Твой график: не нашёл имя {my_name}."

    value = await get_day_value(row, day, month, year)
    if is_work_shift(value):
        return f"✅ Ты работаешь: {detect_shift(value)}"

    return "🏖 Ты отдыхаешь."

async def get_day_schedule(name, day, month=None, year=None):
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

    row, role = await find_row(name, day, month, year)

    if not row:
        return f"Не нашёл график для: {name}"

    role_text = f"\nДолжность: {role}" if role else ""
    value = await get_day_value(row, day, month, year)
    shift = detect_shift(value)
    status = "✅ ты работаешь" if is_work_shift(value) else "🏖 ты отдыхаешь"

    text = f"{name}{role_text}\n\n{format_date(day, month, year)} — {shift}\n{status}"

    people_by_role = await get_people_for_day(day, month, year)
    dept_emojis = {
        "Менеджер": "👔 Менеджер",
        "Официант": "🍽 Официант",
        "Бармен": "🍸 Бармен",
        "Кальян": "💨 Кальян",
        "Хостес": "🙋 Хостес",
    }

    coworkers_text = ""
    for role_key, label in dept_emojis.items():
        people = people_by_role.get(role_key, [])
        filtered = [p for p in people if p.split(" — ")[0].strip() != name]
        if filtered:
            coworkers_text += f"{label}\n" + "\n".join(filtered) + "\n\n"

    total_on_shift = sum(len(v) for v in people_by_role.values())
    if coworkers_text:
        text += f"\n\n👥 {format_date(day, month, year)} работают: всего {total_on_shift}\n\n" + coworkers_text.strip()

    if not is_work_shift(value):
        common_off = await get_common_day_off_people(name, day, month, year)
        if common_off:
            text += f"\n\n🏖 {format_date(day, month, year)} вместе отдыхают:\n" + "\n".join(common_off)

    return text


async def get_range_schedule(name, start_day, end_day, month=None, year=None):
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

        row, role = await find_row(name, day, month, year)

        if row:
            found_any = True
            if role:
                saved_role = role
            value = await get_day_value(row, day, month, year)
        else:
            value = ""

        if role_line_index is None:
            result.append(f"Должность: {saved_role or role or ''}")
            role_line_index = 1
            result.append("")

        result.append(f"{format_date(day, month, year)} — {detect_shift(value)}")

    if unpublished_start is not None:
        if role_line_index is None:
            result.append(f"Должность: {saved_role or ''}")
            role_line_index = 1
            result.append("")
        if unpublished_start == end_day:
            result.append(f"{unpublished_start} {MONTHS[month]} — график пока не составлен")
        else:
            result.append(f"{unpublished_start}–{end_day} {MONTHS[month]} — график пока не составлен")

    if not found_any:
        return f"Не нашёл график для: {name}"

    if saved_role and role_line_index is not None:
        result[role_line_index] = f"Должность: {saved_role}"

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

    dept_emojis = {
        "Менеджер": "👔 Менеджер",
        "Официант": "🍽 Официант",
        "Бармен": "🍸 Бармен",
        "Кальян": "💨 Кальян",
        "Хостес": "🙋 Хостес",
    }

    total = sum(len(v) for v in result.values())
    text = f"👥 {format_date(day, month, year)} работают: всего {total}\n\n"
    text += my_status + "\n\n"

    has_any = False
    for role_key, label in dept_emojis.items():
        people = result.get(role_key, [])
        if people:
            has_any = True
            text += f"{label} ({len(people)})\n" + "\n".join(people) + "\n\n"

    if not has_any:
        text += "Никто не работает."

    return text.strip()

async def find_next_shift(name, from_day, from_month=None, from_year=None):
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
            row, _ = await find_row(name, d, m, y)
            if not row:
                continue
            value = await get_day_value(row, d, m, y)
            if is_work_shift(value):
                return target, value
        except ValueError:
            continue

    return None, None

async def get_notification_text(name):
    now = now_local()
    today = now.day
    month = now.month
    year = now.year

    if not is_day_published(today, month, year):
        next_dt, next_value = await find_next_shift(name, today, month, year)
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

    row, _ = await find_row(name, today, month, year)
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

    next_dt, next_value = await find_next_shift(name, today, month, year)
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
    user = get_user(user_id)

    if not user or not user[1]:
        return "Сначала выбери своё имя."

    my_name = user[1]
    selected = sorted(compare_selected.get(user_id, set()))

    if not selected:
        return "Добавь хотя бы одного сотрудника для сравнения."

    all_people = [my_name] + selected

    period_start, period_end = current_period()

    common_work = []
    common_off = []

    for day in range(period_start, period_end + 1):
        values = {}

        for name in all_people:
            row, _ = await find_row(name, day)
            if not row:
                return f"Не смог найти график для: {name}"
            values[name] = await get_day_value(row, day)

        all_work = all(is_work_shift(value) for value in values.values())
        all_off = all(not is_work_shift(value) for value in values.values())

        if all_work:
            shifts_text = " / ".join([f"{name}: {detect_shift(values[name])}" for name in all_people])
            common_work.append(f"{format_date(day)} — {shifts_text}")

        if all_off:
            common_off.append(f"{format_date(day)}")

    text = "🤝 Совпадения по группе\n\n"
    text += "Участники:\n" + "\n".join([f"• {name}" for name in all_people])
    text += f"\n\nПериод: {period_start}–{period_end}\n\n"

    text += "✅ Все работают в один день:\n"
    text += "\n".join(common_work) if common_work else "нет"
    text += "\n\n"

    text += "🏖 Все отдыхают в один день:\n"
    text += "\n".join(common_off) if common_off else "нет"

    return text

def active_name(user_id):
    if user_id in viewing_colleague:
        return viewing_colleague[user_id]

    return get_user_name(user_id)

async def notification_loop(bot):
    sent = {}

    while True:
        now = now_local()
        current_time = now.strftime("%H:%M")
        today_key = now.strftime("%Y-%m-%d")

        for user_id, name, notify_time in get_notify_users():
            if notify_time != current_time:
                continue

            key = f"{user_id}-{today_key}-{notify_time}"

            if sent.get(key):
                continue

            text = await get_notification_text(name)

            if text:
                await bot.send_message(user_id, text)

            sent[key] = True

        await asyncio.sleep(10)

@dp.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    reset_modes(user_id)

    user = get_user(user_id)

    if user and user[1]:
        await message.answer(
            f"Привет 👋\nТвоё имя: {user[1]}\n\nВыбери раздел:",
            reply_markup=main_kb(user_id)
        )
    else:
        selecting_own_name.add(user_id)
        await message.answer("Сначала выбери своё подразделение:", reply_markup=dep_kb())

@dp.message(F.text == "🏠 Главное меню")
async def home(message: Message):
    user_id = message.from_user.id
    reset_modes(user_id)

    await message.answer("Главное меню:", reply_markup=main_kb(user_id))

@dp.message(F.text == "📌 Мой график")
async def my_schedule_menu(message: Message):
    user_id = message.from_user.id
    viewing_colleague.pop(user_id, None)
    reset_compare_mode(user_id)

    await message.answer("📌 Мой график:", reply_markup=my_schedule_kb())

@dp.message(F.text == "📆 График сегодня/завтра")
async def today_tomorrow_menu(message: Message):
    await message.answer("📆 График сегодня/завтра:", reply_markup=today_tomorrow_kb())

@dp.message(F.text == "⬅️ Вернуться к себе")
async def back_to_self(message: Message):
    user_id = message.from_user.id
    viewing_colleague.pop(user_id, None)
    reset_compare_mode(user_id)

    name = get_user_name(user_id) or "не выбрано"

    await message.answer(
        f"Ты вернулся к своему графику.\nТвоё имя: {name}",
        reply_markup=main_kb(user_id)
    )

@dp.message(F.text == "⬅️ Назад к коллеге")
async def back_to_colleague(message: Message):
    user_id = message.from_user.id
    comparing_users.discard(user_id)

    colleague_name = viewing_colleague.get(user_id)

    if not colleague_name:
        return await message.answer("Коллега не выбран.", reply_markup=main_kb(user_id))

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

@dp.message(F.text.in_(list(DEPARTMENTS.keys())))
async def department_selected(message: Message):
    user_id = message.from_user.id
    department = message.text

    if user_id in comparing_users:
        await message.answer("Выбери сотрудника для сравнения:", reply_markup=compare_names_kb(department, user_id))
    elif user_id in selecting_colleague:
        await message.answer("Выбери коллегу:", reply_markup=colleague_names_kb(department, user_id))
    else:
        selecting_own_name.add(user_id)
        await message.answer("Выбери своё имя:", reply_markup=own_names_kb(department))

@dp.message(F.text.in_(ALL_NAMES))
async def own_name_selected(message: Message):
    user_id = message.from_user.id

    save_user(user_id, name=message.text, notify=0, notify_time='')
    reset_modes(user_id)

    await message.answer(
        f"Имя сохранено: {message.text}",
        reply_markup=main_kb(user_id)
    )

@dp.message(F.text.startswith("👀 "))
async def colleague_selected(message: Message):
    user_id = message.from_user.id
    colleague_name = message.text.replace("👀 ", "").strip()

    viewing_colleague[user_id] = colleague_name
    selecting_colleague.discard(user_id)

    compare_selected[user_id] = {colleague_name}

    await message.answer(
        f"👀 Ты смотришь график коллеги: {colleague_name}",
        reply_markup=colleague_kb()
    )

@dp.message(F.text.startswith("➕ "))
async def compare_person_selected(message: Message):
    user_id = message.from_user.id
    name = message.text.replace("➕ ", "").strip()

    my_name = get_user_name(user_id)

    if name == my_name:
        return await message.answer("Себя добавлять не нужно — ты уже участвуешь в сравнении.")

    if user_id not in compare_selected:
        compare_selected[user_id] = set()

    compare_selected[user_id].add(name)

    await message.answer(
        f"Добавил: {name}\n\n" + selected_compare_text(user_id),
        reply_markup=compare_kb()
    )

@dp.message((F.text.startswith("✅ ")) & (F.text != "✅ Посчитать совпадения"))
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
            reply_markup=main_kb(user_id)
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
async def calculate_compare(message: Message):
    user_id = message.from_user.id

    result = await compare_multiple(user_id)

    await loading_answer(message, "⏳ Сравниваю графики...", result, reply_markup=compare_kb())

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
    name = active_name(message.from_user.id)

    if not name:
        selecting_own_name.add(message.from_user.id)
        return await message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())

    result = await safe_schedule(get_day_schedule(name, now_local().day))
    await loading_answer(message, "⏳ Смотрю график на сегодня...", result)

@dp.message(F.text == "📆 Завтра")
async def tomorrow(message: Message):
    name = active_name(message.from_user.id)

    if not name:
        selecting_own_name.add(message.from_user.id)
        return await message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())

    tomorrow_dt = now_local() + timedelta(days=1)
    result = await safe_schedule(get_day_schedule(name, tomorrow_dt.day, tomorrow_dt.month, tomorrow_dt.year))
    await loading_answer(message, "⏳ Смотрю график на завтра...", result)

@dp.message(F.text == "🗓 Неделя")
async def week(message: Message):
    name = active_name(message.from_user.id)

    if not name:
        selecting_own_name.add(message.from_user.id)
        return await message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())

    now = now_local()
    weekday = now.weekday()
    week_start = now - timedelta(days=weekday)
    week_days = [week_start + timedelta(days=i) for i in range(7)]

    # Сохраняем неделю пользователя
    user_week[message.from_user.id] = week_days

    WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    RU_MONTHS_SHORT = ["", "янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]

    # Краткий обзор недели
    first = week_days[0]
    last = week_days[-1]
    if first.month == last.month:
        header = f"🗓 Неделя: {first.day}–{last.day} {MONTHS[first.month]}"
    else:
        header = f"🗓 Неделя: {first.day} {RU_MONTHS_SHORT[first.month]} – {last.day} {RU_MONTHS_SHORT[last.month]}"

    lines = [header, ""]
    for dt in week_days:
        is_weekend = dt.weekday() >= 5 or (dt.month, dt.day) in RU_HOLIDAYS
        day_label = f"{WEEKDAYS_SHORT[dt.weekday()]} {dt.day}"
        if is_weekend:
            day_label += " ❗"

        try:
            row, _ = await find_row(name, dt.day, dt.month, dt.year)
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

    await loading_answer(message, "⏳ Собираю график на неделю...", "\n".join(lines), reply_markup=week_kb(week_days))

@dp.message(F.text.regexp(r"^📅 (Пн|Вт|Ср|Чт|Пт|Сб|Вс) \d+$"))
async def week_day_detail(message: Message):
    user_id = message.from_user.id
    name = active_name(user_id)

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

    result = await get_day_schedule(name, target.day, target.month, target.year)
    WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    day_label = f"{WEEKDAYS_SHORT[target.weekday()]} {target.day} {MONTHS[target.month]}"
    await loading_answer(message, f"⏳ Смотрю {day_label}...", result, reply_markup=week_kb(week_days))

@dp.message(F.text == "📋 Весь график")
@dp.message(F.text == "📋 Выбрать месяц")
async def choose_month(message: Message):
    await message.answer("Выбери месяц:", reply_markup=months_kb())

@dp.message(F.text.regexp(r"^📋 \w+ \d{4}$"))
async def full_schedule(message: Message):
    name = active_name(message.from_user.id)

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

    max_day = calendar.monthrange(year, month)[1]
    result = await safe_schedule(get_range_schedule(name, 1, max_day, month, year))
    await loading_answer(message, "⏳ Собираю полный график...", result, reply_markup=my_schedule_kb())

@dp.message(F.text == "👥 Кто сегодня")
async def who_today(message: Message):
    result = await safe_schedule(get_people(now_local().day, message.from_user.id))
    await loading_answer(message, "⏳ Проверяю, кто работает сегодня...", result)

@dp.message(F.text == "👥 Кто завтра")
async def who_tomorrow(message: Message):
    tomorrow_dt = now_local() + timedelta(days=1)
    result = await safe_schedule(get_people(tomorrow_dt.day, message.from_user.id, tomorrow_dt.month, tomorrow_dt.year))
    await loading_answer(message, "⏳ Проверяю, кто работает завтра...", result)

@dp.message(F.text == "🔔 Уведомления")
async def notifications_menu(message: Message):
    user_id = message.from_user.id

    if user_id in viewing_colleague:
        return await message.answer(
            "Уведомления можно настраивать только для своего имени.\nНажми «⬅️ Вернуться к себе».",
            reply_markup=colleague_kb()
        )

    user = get_user(user_id)

    if not user or not user[1]:
        selecting_own_name.add(user_id)
        return await message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())

    status = "включены 🔔" if user[2] else "выключены 🔕"
    notify_time = user[3] or "не задано"

    await message.answer(
        f"🔔 Настройки уведомлений\n\nИмя: {user[1]}\nСтатус: {status}\nВремя: {notify_time}",
        reply_markup=notifications_kb()
    )

@dp.message(F.text == "🔔 Включить")
async def notifications_on(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)

    if not user or not user[1]:
        selecting_own_name.add(user_id)
        return await message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())

    if not user[3]:
        waiting_for_time.add(user_id)
        return await message.answer("Сначала задай время уведомления. Например: 09:30")

    save_user(user_id, notify=1)

    await message.answer(
        f"Уведомления включены 🔔\nВремя: {user[3]}",
        reply_markup=main_kb(user_id)
    )

@dp.message(F.text == "🔕 Выключить")
async def notifications_off(message: Message):
    save_user(message.from_user.id, notify=0)
    waiting_for_time.discard(message.from_user.id)

    await message.answer("Уведомления выключены 🔕", reply_markup=main_kb(message.from_user.id))

@dp.message(F.text == "✍️ Задать время")
async def ask_notification_time(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)

    if not user or not user[1]:
        selecting_own_name.add(user_id)
        return await message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())

    waiting_for_time.add(user_id)

    await message.answer("Напиши время уведомления в формате ЧЧ:ММ\n\nНапример: 09:30")

@dp.message()
async def text_handler(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()

    if user_id in waiting_for_time:
        if not is_valid_time(text):
            return await message.answer("Неверный формат. Напиши так: 09:30")

        save_user(user_id, notify_time=text, notify=1)
        waiting_for_time.discard(user_id)

        return await message.answer(
            f"Время уведомлений сохранено: {text}\nУведомления включены 🔔",
            reply_markup=main_kb(user_id)
        )

    await message.answer("Используй кнопки ниже.", reply_markup=main_kb(user_id))

async def main():
    if not BOT_TOKEN:
        print("Ошибка: BOT_TOKEN не найден в .env")
        return

    bot = Bot(token=BOT_TOKEN)

    await load_full_sheet()

    asyncio.create_task(notification_loop(bot))

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
