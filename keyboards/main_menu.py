from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from repositories.users_repo import get_user_name


def main_kb(user_id, name: str = "Моё имя"):
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📌 Мой график"), KeyboardButton(text="📆 График сегодня/завтра")],
            [KeyboardButton(text="👀 Коллеги"), KeyboardButton(text="🔔 Уведомления")],
            [KeyboardButton(text="💰 Зарплата"), KeyboardButton(text=f"👤 {name}")],
        ],
        resize_keyboard=True,
    )


async def main_kb_async(user_id: int) -> ReplyKeyboardMarkup:
    name = await get_user_name(user_id) or "Моё имя"
    return main_kb(user_id, name)
