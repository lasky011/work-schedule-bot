from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from constants import SHEET_GID_MAP
from departments_manager import DEPARTMENTS
from keyboards import context
from repositories.users_repo import get_user_name


def my_schedule_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📆 Завтра")],
            [KeyboardButton(text="🗓 Недели"), KeyboardButton(text="📋 Выбрать месяц")],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True,
    )


def months_kb():
    """Динамически строит кнопки из SHEET_GID_MAP"""
    seen = set()
    buttons = []
    for (year, month, period) in sorted(SHEET_GID_MAP.keys()):
        key = (year, month)
        if key not in seen:
            seen.add(key)
            month_name = context.MONTHS_NOM[month]
            buttons.append([KeyboardButton(text=f"📋 {month_name} {year}")])
    buttons.append([KeyboardButton(text="🏠 Главное меню")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def today_tomorrow_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👥 Кто сегодня"), KeyboardButton(text="👥 Кто завтра")],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True,
    )


def colleague_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📆 Завтра")],
            [KeyboardButton(text="🗓 Недели"), KeyboardButton(text="📋 Весь график")],
            [KeyboardButton(text="🤝 Совпадения")],
            [KeyboardButton(text="⬅️ Вернуться к себе")],
        ],
        resize_keyboard=True,
    )


def dep_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👔 Менеджер"), KeyboardButton(text="🍽 Официант")],
            [KeyboardButton(text="🍸 Бармен"), KeyboardButton(text="💨 Кальян")],
            [KeyboardButton(text="🙋 Хостес")],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True,
    )


def own_names_kb(department):
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=name)] for name in DEPARTMENTS[department]]
        + [[KeyboardButton(text="🏠 Главное меню")]],
        resize_keyboard=True,
    )


async def colleague_names_kb(department, user_id):
    my_name = await get_user_name(user_id)
    buttons = []

    for name in DEPARTMENTS[department]:
        if name != my_name:
            buttons.append([KeyboardButton(text=f"👀 {name}")])

    buttons.append([KeyboardButton(text="🏠 Главное меню")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


async def compare_names_kb(department, user_id, selected: set | None = None):
    my_name = await get_user_name(user_id)
    selected = selected or set()
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
