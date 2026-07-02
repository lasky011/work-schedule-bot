"""Календарь для внесения смен — русская локализация, без лишних кнопок."""

import calendar as cal_mod
from datetime import datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram_calendar import SimpleCalendar
from aiogram_calendar.schemas import SimpleCalAct, SimpleCalendarCallback, highlight, superscript

RU_DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
RU_MONTHS = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


class ShiftCalendar(SimpleCalendar):
    """Календарь без «Сегодня»/«Отмена» — они есть на reply-клавиатуре."""

    async def start_calendar(
        self,
        year: int | None = None,
        month: int | None = None,
    ) -> InlineKeyboardMarkup:
        today = datetime.now()
        year = year or today.year
        month = month or today.month
        now_month, now_year, now_day = today.month, today.year, today.day

        def highlight_month():
            month_str = self._labels.months[month - 1]
            if now_month == month and now_year == year:
                return highlight(month_str)
            return month_str

        def format_day_string(day: int):
            date_to_check = datetime(year, month, day)
            if self.min_date and date_to_check < self.min_date:
                return superscript(str(day))
            if self.max_date and date_to_check > self.max_date:
                return superscript(str(day))
            return str(day)

        def highlight_day(day: int):
            day_string = format_day_string(day)
            if now_month == month and now_year == year and now_day == day:
                return highlight(day_string)
            return day_string

        kb = []

        kb.append([
            InlineKeyboardButton(
                text="<<",
                callback_data=SimpleCalendarCallback(
                    act=SimpleCalAct.prev_y, year=year, month=month, day=1,
                ).pack(),
            ),
            InlineKeyboardButton(
                text=str(year) if year != now_year else highlight(year),
                callback_data=self.ignore_callback,
            ),
            InlineKeyboardButton(
                text=">>",
                callback_data=SimpleCalendarCallback(
                    act=SimpleCalAct.next_y, year=year, month=month, day=1,
                ).pack(),
            ),
        ])

        kb.append([
            InlineKeyboardButton(
                text="<",
                callback_data=SimpleCalendarCallback(
                    act=SimpleCalAct.prev_m, year=year, month=month, day=1,
                ).pack(),
            ),
            InlineKeyboardButton(text=highlight_month(), callback_data=self.ignore_callback),
            InlineKeyboardButton(
                text=">",
                callback_data=SimpleCalendarCallback(
                    act=SimpleCalAct.next_m, year=year, month=month, day=1,
                ).pack(),
            ),
        ])

        week_header = []
        for i, weekday in enumerate(self._labels.days_of_week):
            if now_month == month and now_year == year and today.weekday() == i:
                week_header.append(InlineKeyboardButton(text=highlight(weekday), callback_data=self.ignore_callback))
            else:
                week_header.append(InlineKeyboardButton(text=weekday, callback_data=self.ignore_callback))
        kb.append(week_header)

        for week in cal_mod.monthcalendar(year, month):
            days_row = []
            for day in week:
                if day == 0:
                    days_row.append(InlineKeyboardButton(text=" ", callback_data=self.ignore_callback))
                    continue
                days_row.append(InlineKeyboardButton(
                    text=highlight_day(day),
                    callback_data=SimpleCalendarCallback(
                        act=SimpleCalAct.day, year=year, month=month, day=day,
                    ).pack(),
                ))
            kb.append(days_row)

        return InlineKeyboardMarkup(row_width=7, inline_keyboard=kb)


def shift_calendar() -> ShiftCalendar:
    cal = ShiftCalendar()
    cal._labels.days_of_week = list(RU_DAYS)
    cal._labels.months = list(RU_MONTHS)
    return cal
