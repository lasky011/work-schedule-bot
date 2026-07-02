"""Inline-кнопки для учёта смен."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

CB_SHIFT_ENTRY = "shift_entry:"


def shift_entry_kb(date_str: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏱ Внести смену", callback_data=f"{CB_SHIFT_ENTRY}{date_str}")],
        ]
    )
