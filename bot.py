import asyncio
import os
import calendar
import logging
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

# 1-15
GID_FIRST = "1690889478"

# 16-31
GID_SECOND = "1467004546"


def build_csv_url(gid):
    return (
        f"https://docs.google.com/spreadsheets/d/"
        f"{SHEET_ID}/export?format=csv&gid={gid}"
    )


dp = Dispatcher()

cached_df = None
cached_time = None
cache_lock = asyncio.Lock()

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

ROLES = [
    "Менеджер",
    "Официант",
    "Бармен",
    "Кальян",
    "Хостес",
]

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

WEEKDAYS = [
    "пн",
    "вт",
    "ср",
    "чт",
    "пт",
    "сб",
    "вс",
]

RU_HOLIDAYS = {
    (1, 1), (1, 2), (1, 3), (1, 4),
    (1, 5), (1, 6), (1, 7), (1, 8),
    (2, 23),
    (3, 8),
    (5, 1),
    (5, 9),
    (6, 12),
    (11, 4),
}

user_names = {}

viewing_colleague = {}


def main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📅 Сегодня"),
                KeyboardButton(text="📆 Завтра"),
            ],
            [
                KeyboardButton(text="🗓 Неделя"),
                KeyboardButton(text="📋 Весь график"),
            ],
            [
                KeyboardButton(text="👥 Кто сегодня"),
                KeyboardButton(text="👥 Кто завтра"),
            ],
            [
                KeyboardButton(text="👀 Коллеги"),
            ],
        ],
        resize_keyboard=True
    )


def dep_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="👔 Менеджер"),
                KeyboardButton(text="🍽 Официант"),
            ],
            [
                KeyboardButton(text="🍸 Бармен"),
                KeyboardButton(text="💨 Кальян"),
            ],
            [
                KeyboardButton(text="🙋 Хостес"),
            ],
        ],
        resize_keyboard=True
    )


def names_kb(dep):
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=name)]
            for name in DEPARTMENTS[dep]
        ],
        resize_keyboard=True
    )


async def download_sheet(gid):
    url = build_csv_url(gid)

    def sync():
        r = requests.get(url, timeout=10)

        r.raise_for_status()
        r.encoding = "utf-8"

        return pd.read_csv(StringIO(r.text), header=None)

    return await asyncio.to_thread(sync)


async def load_full_sheet():
    global cached_df
    global cached_time

    async with cache_lock:
        now = now_local()

        if cached_df is not None and cached_time is not None:
            age = (now - cached_time).total_seconds()

            if age < 60:
                return cached_df

        df1 = await download_sheet(GID_FIRST)
        df2 = await download_sheet(GID_SECOND)

        df = pd.concat([df1, df2], ignore_index=True)

        cached_df = df
        cached_time = now

        return df


def clean_value(value):
    text = str(value).strip()

    if text.lower() in [
        "",
        "nan",
        "none",
        "-",
        "—",
        "выходной",
    ]:
        return ""

    return text


def is_work_shift(value):
    value = clean_value(value)

    if not value:
        return False

    if ":" in value:
        return True

    if value.startswith(("9", "10", "11", "12", "13", "14", "15", "16")):
        return True

    return False


def detect_shift(value):
    value = clean_value(value)

    if not value:
        return "выходной"

    if value.startswith(("9", "10", "11")):
        return f"{value} — утро"

    if value.startswith(("12", "13", "14", "15", "16")):
        return f"{value} — вечер"

    return value


def weekday_label(day):
    now = now_local()

    try:
        weekday_index = datetime(
            now.year,
            now.month,
            day
        ).weekday()
    except:
        return ""

    label = WEEKDAYS[weekday_index]

    is_red = (
        weekday_index >= 4
        or (now.month, day) in RU_HOLIDAYS
    )

    if is_red:
        return f"❗ {label}"

    return label


def format_date(day):
    return (
        f"{day} "
        f"{MONTHS[now_local().month]} "
        f"({weekday_label(day)})"
    )


def days_in_month():
    now = now_local()

    return calendar.monthrange(
        now.year,
        now.month
    )[1]


def get_day_column(df, day):
    target = str(day)

    for i in range(len(df)):
        row = df.iloc[i].fillna("").astype(str).tolist()

        for col_index, value in enumerate(row):
            if str(value).strip() == target:
                return col_index

    return None


async def find_row(name, day):
    df = await load_sheet(now_local().day)

    role = None

    for i in range(len(df)):
        first = str(df.iloc[i, 0]).strip()

        if first in ROLES:
            role = first
            continue

        row = df.iloc[i].fillna("").astype(str).tolist()

        row_text = " ".join(row).lower()

        if name.lower() in row_text:
            return row, role

    return None, None


async def get_day_value(row, day):
    df = await load_sheet(now_local().day)

    col = get_day_column(df, day)

    if col is None:
        return ""

    if col >= len(row):
        return ""

    return row[col]


async def get_people_for_day(day):
    df = await load_sheet(now_local().day)

    col = get_day_column(df, day)

    if col is None:
        return {}

    result = {}
    role = None

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
                result[role].append(
                    f"{name} — {detect_shift(value)}"
                )

    return result


async def get_day_schedule(name, day):
    row, role = await find_row(name, day)

    if not row:
        return f"Не нашёл график для: {name}"

    value = await get_day_value(row, day)

    status = (
        "✅ ты работаешь"
        if is_work_shift(value)
        else "🏖 ты отдыхаешь"
    )

    text = (
        f"{name}\n"
        f"Должность: {role}\n\n"
        f"{format_date(day)} — {detect_shift(value)}\n"
        f"{status}"
    )

    people = await get_people_for_day(day)

    coworkers = []

    for role_name, items in people.items():
        for item in items:
            person_name = item.split(" — ")[0]

            if person_name != name:
                coworkers.append(item)

    if coworkers:
        text += (
            f"\n\n👥 {format_date(day)} работают:\n"
            + "\n".join(coworkers)
        )

    return text


async def get_range_schedule(name, start_day, end_day):
    row, role = await find_row(name, day)

    if not row:
        return f"Не нашёл график для: {name}"

    result = [
        name,
        f"Должность: {role}",
        "",
    ]

    max_day = days_in_month()

    for day in range(start_day, end_day + 1):
        if day > max_day:
            break

        value = await get_day_value(row, day)

        result.append(
            f"{format_date(day)} — {detect_shift(value)}"
        )

    return "\n".join(result)


async def get_people(day):
    result = await get_people_for_day(day)

    text = f"👥 {format_date(day)} работают:\n\n"

    for role_name, people in result.items():
        if people:
            text += (
                f"{role_name}\n"
                + "\n".join(people)
                + "\n\n"
            )

    return text.strip()


def active_name(user_id):
    if user_id in viewing_colleague:
        return viewing_colleague[user_id]

    return user_names.get(user_id)


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Выбери подразделение:",
        reply_markup=dep_kb()
    )


@dp.message(F.text.in_(list(DEPARTMENTS.keys())))
async def dep_selected(message: Message):
    await message.answer(
        "Выбери имя:",
        reply_markup=names_kb(message.text)
    )


@dp.message(F.text.in_(ALL_NAMES))
async def name_selected(message: Message):
    user_names[message.from_user.id] = message.text

    viewing_colleague.pop(message.from_user.id, None)

    await message.answer(
        f"Имя сохранено: {message.text}",
        reply_markup=main_kb()
    )


@dp.message(F.text == "👀 Коллеги")
async def colleagues(message: Message):
    await message.answer(
        "Выбери подразделение коллеги:",
        reply_markup=dep_kb()
    )


@dp.message(F.text.startswith("👀 "))
async def colleague_selected(message: Message):
    name = message.text.replace("👀 ", "").strip()

    viewing_colleague[message.from_user.id] = name

    await message.answer(
        f"Теперь смотришь график: {name}",
        reply_markup=main_kb()
    )


@dp.message(F.text == "📅 Сегодня")
async def today(message: Message):
    name = active_name(message.from_user.id)

    if not name:
        return await message.answer(
            "Сначала выбери имя."
        )

    result = await get_day_schedule(
        name,
        now_local().day
    )

    await message.answer(result)


@dp.message(F.text == "📆 Завтра")
async def tomorrow(message: Message):
    name = active_name(message.from_user.id)

    if not name:
        return await message.answer(
            "Сначала выбери имя."
        )

    tomorrow_day = (
        now_local() + timedelta(days=1)
    ).day

    result = await get_day_schedule(
        name,
        tomorrow_day
    )

    await message.answer(result)


@dp.message(F.text == "🗓 Неделя")
async def week(message: Message):
    name = active_name(message.from_user.id)

    if not name:
        return await message.answer(
            "Сначала выбери имя."
        )

    start_day = now_local().day

    result = await get_range_schedule(
        name,
        start_day,
        start_day + 6
    )

    await message.answer(result)


@dp.message(F.text == "📋 Весь график")
async def full_schedule(message: Message):
    name = active_name(message.from_user.id)

    if not name:
        return await message.answer(
            "Сначала выбери имя."
        )

    result = await get_range_schedule(
        name,
        1,
        31
    )

    await message.answer(result)


@dp.message(F.text == "👥 Кто сегодня")
async def who_today(message: Message):
    result = await get_people(
        now_local().day
    )

    await message.answer(result)


@dp.message(F.text == "👥 Кто завтра")
async def who_tomorrow(message: Message):
    tomorrow_day = (
        now_local() + timedelta(days=1)
    ).day

    result = await get_people(
        tomorrow_day
    )

    await message.answer(result)


async def main():
    logging.basicConfig(level=logging.INFO)

    if not BOT_TOKEN:
        print("BOT_TOKEN not found")
        return

    bot = Bot(token=BOT_TOKEN)

    await load_sheet(now_local().day)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
