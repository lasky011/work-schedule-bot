"""Inline-клавиатуры для навигации по неделе."""

from datetime import datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

CB_WEEK_PREV = "wk:prev"
CB_WEEK_NEXT = "wk:next"
CB_WEEK_DAY = "wk:day:"


def week_inline_kb(week_days) -> InlineKeyboardMarkup:
    weekdays_short = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    rows = []
    day_row = []

    for dt in week_days:
        label = f"{weekdays_short[dt.weekday()]} {dt.day}"
        day_row.append(
            InlineKeyboardButton(
                text=label,
                callback_data=f"{CB_WEEK_DAY}{dt.strftime('%Y-%m-%d')}",
            )
        )
        if len(day_row) == 4:
            rows.append(day_row)
            day_row = []
    if day_row:
        rows.append(day_row)

    rows.append([
        InlineKeyboardButton(text="◀️ Пред.", callback_data=CB_WEEK_PREV),
        InlineKeyboardButton(text="След. ▶️", callback_data=CB_WEEK_NEXT),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
