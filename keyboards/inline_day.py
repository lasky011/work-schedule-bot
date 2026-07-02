"""Inline-кнопки под карточкой дня."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

CB_WHO_TOMORROW = "day:who_tmr"


def today_actions_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Кто завтра на смене", callback_data=CB_WHO_TOMORROW)],
        ]
    )
