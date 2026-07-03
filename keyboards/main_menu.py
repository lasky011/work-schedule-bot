from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from repositories.users_repo import get_user_name


def main_kb(user_id, name: str = "Моё имя"):
    rows = [
        [KeyboardButton(text="📅 Сегодня")],
        [KeyboardButton(text=f"👤 {name}")],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


async def main_kb_async(user_id: int) -> ReplyKeyboardMarkup:
    name = await get_user_name(user_id) or "Моё имя"
    return main_kb(user_id, name)
