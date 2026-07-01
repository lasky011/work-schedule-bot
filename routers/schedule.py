"""Роутер просмотра графика."""

import asyncio
import calendar
from datetime import timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app_config import now_local
from fsm_context import (
    active_name,
    active_role,
    clear_colleague_view,
    get_user_week,
    prompt_choose_own_name,
    reset_compare_mode,
    set_user_week,
)
from keyboards import context as kb_context
from keyboards import (
    months_kb,
    my_schedule_kb,
    today_tomorrow_kb,
    week_kb,
)
from schedule_utils import detect_shift, is_work_shift
from services import schedule_service as schedule
from ui_utils import MIN_LOADING_SEC, loading_answer

router = Router(name="schedule")


@router.message(F.text == "📌 Мой график")
async def my_schedule_menu(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await clear_colleague_view(state)
    await reset_compare_mode(state)

    name = await active_name(user_id, state)
    loading = await message.answer("⏳ Загружаю твой график...")
    t0 = asyncio.get_event_loop().time()

    role = await active_role(user_id, state)
    today_line = ""
    if name:
        now = now_local()
        try:
            row, _ = await schedule.find_row(name, now.day, now.month, now.year, target_role=role)
            if row:
                value = await schedule.get_day_value(row, now.day, now.month, now.year)
                if is_work_shift(value):
                    today_line = f"\n\n📅 Сегодня работаешь — {detect_shift(value)}"
                else:
                    today_line = "\n\n🏖 Сегодня выходной"
            else:
                today_line = "\n\n📋 График на сегодня ещё не составлен"
        except Exception:
            pass

    elapsed = asyncio.get_event_loop().time() - t0
    if elapsed < MIN_LOADING_SEC:
        await asyncio.sleep(MIN_LOADING_SEC - elapsed)
    try:
        await loading.delete()
    except Exception:
        pass
    await message.answer(f"📌 Мой график{today_line}", reply_markup=my_schedule_kb())


@router.message(F.text == "📆 График сегодня/завтра")
async def today_tomorrow_menu(message: Message):
    await message.answer("📆 График сегодня/завтра:", reply_markup=today_tomorrow_kb())


@router.message(F.text == "📅 Сегодня")
async def today(message: Message, state: FSMContext):
    name = await active_name(message.from_user.id, state)
    if not name:
        return await prompt_choose_own_name(message, state)

    role = await active_role(message.from_user.id, state)
    await loading_answer(
        message, "⏳ Загружаю твой график...",
        schedule.get_day_schedule(name, now_local().day, target_role=role),
        reply_markup=my_schedule_kb(),
    )


@router.message(F.text == "📆 Завтра")
async def tomorrow(message: Message, state: FSMContext):
    name = await active_name(message.from_user.id, state)
    if not name:
        return await prompt_choose_own_name(message, state)

    role = await active_role(message.from_user.id, state)
    tomorrow_dt = now_local() + timedelta(days=1)
    await loading_answer(
        message, "⏳ Загружаю график на завтра...",
        schedule.get_day_schedule(
            name, tomorrow_dt.day, tomorrow_dt.month, tomorrow_dt.year, target_role=role,
        ),
        reply_markup=my_schedule_kb(),
    )


async def _show_week_schedule(message: Message, week_start_dt, state: FSMContext):
    user_id = message.from_user.id
    name = await active_name(user_id, state)

    if not name:
        return await prompt_choose_own_name(message, state)

    role = await active_role(user_id, state)
    week_days = [week_start_dt + timedelta(days=i) for i in range(7)]
    await set_user_week(state, week_days)

    loading = await message.answer("⏳ Собираю график на неделю...")
    t0 = asyncio.get_event_loop().time()

    weekdays_short = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    ru_months_short = ["", "янв", "фев", "мар", "апр", "май", "июн",
                       "июл", "авг", "сен", "окт", "ноя", "дек"]

    first = week_days[0]
    last = week_days[-1]
    if first.month == last.month:
        header = f"🗓 Неделя: {first.day}–{last.day} {schedule.MONTHS[first.month]}"
    else:
        header = (
            f"🗓 Неделя: {first.day} {ru_months_short[first.month]} – "
            f"{last.day} {ru_months_short[last.month]}"
        )

    lines = [header, ""]
    for dt in week_days:
        is_weekend = dt.weekday() in (4, 5) or (dt.month, dt.day) in (schedule.RU_HOLIDAYS or set())
        day_label = f"{weekdays_short[dt.weekday()]} {dt.day}"
        if is_weekend:
            day_label += " ❗"

        try:
            row, _ = await schedule.find_row(name, dt.day, dt.month, dt.year, target_role=role)
            people_by_role = await schedule.get_people_for_day(dt.day, dt.month, dt.year)
            total_on_shift = sum(len(v) for v in people_by_role.values())
            if row:
                value = await schedule.get_day_value(row, dt.day, dt.month, dt.year)
                if is_work_shift(value):
                    lines.append(f"{day_label} — {detect_shift(value)} ✅ (на смене: {total_on_shift})")
                else:
                    lines.append(f"{day_label} — выходной 🏖 (на смене: {total_on_shift})")
            else:
                lines.append(f"{day_label} — нет данных")
        except (ValueError, ConnectionError):
            lines.append(f"{day_label} — таблица недоступна")

    elapsed = asyncio.get_event_loop().time() - t0
    if elapsed < MIN_LOADING_SEC:
        await asyncio.sleep(MIN_LOADING_SEC - elapsed)
    try:
        await loading.delete()
    except Exception:
        pass
    await message.answer("\n".join(lines), reply_markup=week_kb(week_days))


@router.message(F.text == "🗓 Недели")
async def week(message: Message, state: FSMContext):
    now = now_local()
    week_start = now - timedelta(days=now.weekday())
    await _show_week_schedule(message, week_start, state)


@router.message(F.text == "◀️ Пред. неделя")
async def prev_week(message: Message, state: FSMContext):
    week_days = await get_user_week(state)
    if not week_days:
        return await message.answer("Сначала открой неделю.", reply_markup=my_schedule_kb())
    await _show_week_schedule(message, week_days[0] - timedelta(days=7), state)


@router.message(F.text == "▶️ След. неделя")
async def next_week(message: Message, state: FSMContext):
    week_days = await get_user_week(state)
    if not week_days:
        return await message.answer("Сначала открой неделю.", reply_markup=my_schedule_kb())
    await _show_week_schedule(message, week_days[0] + timedelta(days=7), state)


@router.message(F.text.regexp(r"^📅 (Пн|Вт|Ср|Чт|Пт|Сб|Вс) \d+$"))
async def week_day_detail(message: Message, state: FSMContext):
    user_id = message.from_user.id
    name = await active_name(user_id, state)

    if not name:
        return await prompt_choose_own_name(message, state)

    week_days = await get_user_week(state)
    if not week_days:
        return await message.answer("Сначала открой неделю.", reply_markup=my_schedule_kb())

    parts = message.text.replace("📅 ", "").strip().split()
    day_num = int(parts[1])

    target = None
    for dt in week_days:
        if dt.day == day_num:
            target = dt
            break

    if not target:
        return await message.answer("Не нашёл этот день.", reply_markup=week_kb(week_days))

    weekdays_short = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    day_label = f"{weekdays_short[target.weekday()]} {target.day} {schedule.MONTHS[target.month]}"
    role = await active_role(user_id, state)
    await loading_answer(
        message, f"⏳ Загружаю {day_label}...",
        schedule.get_day_schedule(
            name, target.day, target.month, target.year, target_role=role,
        ),
        reply_markup=week_kb(week_days),
    )


@router.message(F.text == "📋 Весь график")
@router.message(F.text == "📋 Выбрать месяц")
async def choose_month(message: Message):
    await message.answer("Выбери месяц:", reply_markup=months_kb())


@router.message(F.text.regexp(r"^📋 \w+ \d{4}$"))
async def full_schedule(message: Message, state: FSMContext):
    name = await active_name(message.from_user.id, state)
    if not name:
        return await prompt_choose_own_name(message, state)

    parts = message.text.replace("📋 ", "").strip().split()
    month_name = parts[0]
    year = int(parts[1])
    month = kb_context.MONTHS_NOM.index(month_name)

    if month == 0:
        return await message.answer("Не могу определить месяц.", reply_markup=my_schedule_kb())

    role = await active_role(message.from_user.id, state)
    max_day = calendar.monthrange(year, month)[1]
    await loading_answer(
        message, "⏳ Загружаю полный график...",
        schedule.get_range_schedule(name, 1, max_day, month, year, target_role=role),
        reply_markup=my_schedule_kb(),
    )


@router.message(F.text == "👥 Кто сегодня")
async def who_today(message: Message):
    await loading_answer(
        message, "⏳ Проверяю, кто работает сегодня...",
        schedule.get_people(now_local().day, message.from_user.id),
        reply_markup=today_tomorrow_kb(),
    )


@router.message(F.text == "👥 Кто завтра")
async def who_tomorrow(message: Message):
    tomorrow_dt = now_local() + timedelta(days=1)
    await loading_answer(
        message, "⏳ Проверяю, кто работает завтра...",
        schedule.get_people(
            tomorrow_dt.day, message.from_user.id, tomorrow_dt.month, tomorrow_dt.year,
        ),
        reply_markup=today_tomorrow_kb(),
    )
