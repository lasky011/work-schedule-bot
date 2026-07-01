from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def notifications_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔔 Включить"), KeyboardButton(text="🔕 Выключить")],
            [KeyboardButton(text="✍️ Задать время")],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True,
    )
