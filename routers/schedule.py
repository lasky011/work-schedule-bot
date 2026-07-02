"""Роутер просмотра графика."""

import asyncio
import calendar
from datetime import timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app_config import now_local
from fsm_context import (
    active_name,
    active_role,
    clear_colleague_view,
    get_user_week,
    prompt_choose_own_name,
    reset_compare_mode,
    set_user_week,
    with_viewing_context,
)
from keyboards import context as kb_context
from keyboards import (
    main_kb_async,
    months_kb,
    my_schedule_kb,
    week_kb,
)
from keyboards.inline_day import CB_WHO_TOMORROW, today_actions_kb
from keyboards.inline_schedule import CB_WEEK_DAY, CB_WEEK_NEXT, CB_WEEK_PREV, week_inline_kb
import message_format as mf
from schedule_utils import detect_shift, is_work_shift
from services import schedule_service as schedule
from ui_utils import MIN_LOADING_SEC, answer_html, loading_answer

router = Router(name="schedule")


@router.message(F.text == "📅 Сегодня")
async def today(message: Message, state: FSMContext):
    name = await active_name(message.from_user.id, state)
    if not name:
        return await prompt_choose_own_name(message, state)

    role = await active_role(message.from_user.id, state)
    now = now_local()

    async def _load():
        body = await schedule.get_day_schedule(name, now.day, target_role=role)
        return await with_viewing_context(state, body)

    await loading_answer(
        message, "⏳ Загружаю твой график...",
        _load(),
        reply_markup=await _schedule_reply_kb(state),
        inline_markup=today_actions_kb(),
    )


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
                    today_line = f"\n\n📅 Сегодня: ✅ <code>{mf.esc(detect_shift(value))}</code>"
                else:
                    today_line = "\n\n🏖 Сегодня: выходной"
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

    text = await with_viewing_context(state, f"📌 <b>Мой график</b>{today_line}")
    await answer_html(message, text, reply_markup=my_schedule_kb())


@router.message(F.text == "📆 График сегодня/завтра")
async def today_tomorrow_menu(message: Message, state: FSMContext):
    """Старый пункт меню — ведём на «Сегодня»."""
    return await today(message, state)


@router.callback_query(F.data == CB_WHO_TOMORROW)
async def who_tomorrow_inline(callback: CallbackQuery, state: FSMContext):
    tomorrow_dt = now_local() + timedelta(days=1)
    await callback.answer()
    await loading_answer(
        callback.message,
        "⏳ Проверяю, кто работает завтра...",
        schedule.get_people(
            tomorrow_dt.day, callback.from_user.id, tomorrow_dt.month, tomorrow_dt.year,
        ),
        reply_markup=await main_kb_async(callback.from_user.id),
    )


async def _schedule_reply_kb(state: FSMContext):
    from fsm_context import get_viewing_colleague
    if await get_viewing_colleague(state):
        from keyboards import colleague_kb
        return colleague_kb()
    return my_schedule_kb()


@router.message(F.text == "📆 Завтра")
async def tomorrow(message: Message, state: FSMContext):
    name = await active_name(message.from_user.id, state)
    if not name:
        return await prompt_choose_own_name(message, state)

    role = await active_role(message.from_user.id, state)
    tomorrow_dt = now_local() + timedelta(days=1)

    async def _load():
        body = await schedule.get_day_schedule(
            name, tomorrow_dt.day, tomorrow_dt.month, tomorrow_dt.year, target_role=role,
        )
        return await with_viewing_context(state, body)

    await loading_answer(
        message, "⏳ Загружаю график на завтра...",
        _load(),
        reply_markup=await _schedule_reply_kb(state),
    )


async def _show_week_schedule(
    message: Message,
    week_start_dt,
    state: FSMContext,
    user_id: int,
    edit_msg=None,
):
    name = await active_name(user_id, state)

    if not name:
        return await prompt_choose_own_name(message, state)

    role = await active_role(user_id, state)
    week_days = [week_start_dt + timedelta(days=i) for i in range(7)]
    await set_user_week(state, week_days)

    loading = None
    if not edit_msg:
        loading = await message.answer("⏳ Собираю график на неделю...")
    t0 = asyncio.get_event_loop().time()

    weekdays_short = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    ru_months_short = ["", "янв", "фев", "мар", "апр", "май", "июн",
                       "июл", "авг", "сен", "окт", "ноя", "дек"]

    first = week_days[0]
    last = week_days[-1]
    if first.month == last.month:
        header = f"{first.day}–{last.day} {schedule.MONTHS[first.month]}"
    else:
        header = (
            f"{first.day} {ru_months_short[first.month]} – "
            f"{last.day} {ru_months_short[last.month]}"
        )

    day_lines = []
    today = now_local().date()
    for dt in week_days:
        day_short = weekdays_short[dt.weekday()]
        month_short = ru_months_short[dt.month]
        is_today = dt.date() == today
        try:
            row, _ = await schedule.find_row(name, dt.day, dt.month, dt.year, target_role=role)
            if row:
                value = await schedule.get_day_value(row, dt.day, dt.month, dt.year)
                if is_work_shift(value):
                    day_lines.append(
                        mf.week_day_line(
                            day_short, dt.day, month_short, True, detect_shift(value), is_today,
                        )
                    )
                else:
                    day_lines.append(
                        mf.week_day_line(day_short, dt.day, month_short, False, None, is_today)
                    )
            else:
                line = f"{day_short} {dt.day} {month_short} · 📋 нет данных"
                if is_today:
                    line = f"<b>📍 {line}</b>"
                day_lines.append(line)
        except (ValueError, ConnectionError):
            line = f"{day_short} {dt.day} {month_short} · ⚠️ таблица недоступна"
            if is_today:
                line = f"<b>📍 {line}</b>"
            day_lines.append(line)

    body = mf.week_list_block(header, day_lines)
    text = await with_viewing_context(state, body)
    inline = week_inline_kb(week_days, today=today)

    elapsed = asyncio.get_event_loop().time() - t0
    if elapsed < MIN_LOADING_SEC:
        await asyncio.sleep(MIN_LOADING_SEC - elapsed)

    if edit_msg:
        try:
            await edit_msg.edit_text(text, parse_mode=mf.PARSE_MODE, reply_markup=inline)
        except Exception:
            await message.answer(text, parse_mode=mf.PARSE_MODE, reply_markup=inline)
    else:
        try:
            await loading.delete()
        except Exception:
            pass
        await message.answer(text, parse_mode=mf.PARSE_MODE, reply_markup=inline)


@router.message(F.text == "🗓 Недели")
async def week(message: Message, state: FSMContext):
    now = now_local()
    week_start = now - timedelta(days=now.weekday())
    await _show_week_schedule(message, week_start, state, message.from_user.id)


@router.message(F.text == "◀️ Пред. неделя")
async def prev_week(message: Message, state: FSMContext):
    week_days = await get_user_week(state)
    if not week_days:
        return await answer_html(message, "Сначала открой неделю.", reply_markup=my_schedule_kb())
    await _show_week_schedule(
        message, week_days[0] - timedelta(days=7), state, message.from_user.id,
    )


@router.message(F.text == "▶️ След. неделя")
async def next_week(message: Message, state: FSMContext):
    week_days = await get_user_week(state)
    if not week_days:
        return await answer_html(message, "Сначала открой неделю.", reply_markup=my_schedule_kb())
    await _show_week_schedule(
        message, week_days[0] + timedelta(days=7), state, message.from_user.id,
    )


@router.callback_query(F.data == CB_WEEK_PREV)
async def week_inline_prev(callback: CallbackQuery, state: FSMContext):
    week_days = await get_user_week(state)
    if not week_days:
        return await callback.answer("Сначала открой неделю", show_alert=True)
    await callback.answer()
    await _show_week_schedule(
        callback.message,
        week_days[0] - timedelta(days=7),
        state,
        callback.from_user.id,
        edit_msg=callback.message,
    )


@router.callback_query(F.data == CB_WEEK_NEXT)
async def week_inline_next(callback: CallbackQuery, state: FSMContext):
    week_days = await get_user_week(state)
    if not week_days:
        return await callback.answer("Сначала открой неделю", show_alert=True)
    await callback.answer()
    await _show_week_schedule(
        callback.message,
        week_days[0] + timedelta(days=7),
        state,
        callback.from_user.id,
        edit_msg=callback.message,
    )


@router.callback_query(F.data.startswith(CB_WEEK_DAY))
async def week_inline_day(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    name = await active_name(user_id, state)
    if not name:
        return await callback.answer("Сначала выбери имя", show_alert=True)

    date_str = callback.data[len(CB_WEEK_DAY):]
    target = now_local().replace(
        year=int(date_str[:4]),
        month=int(date_str[5:7]),
        day=int(date_str[8:10]),
        hour=0, minute=0, second=0, microsecond=0,
    )
    role = await active_role(user_id, state)

    async def _load():
        body = await schedule.get_day_schedule(
            name, target.day, target.month, target.year, target_role=role,
        )
        return await with_viewing_context(state, body)

    await callback.answer()
    await loading_answer(
        callback.message,
        f"⏳ Загружаю {target.day} число...",
        _load(),
        reply_markup=week_kb(await get_user_week(state) or []),
    )


@router.message(F.text.regexp(r"^📅 (Пн|Вт|Ср|Чт|Пт|Сб|Вс) \d+$"))
async def week_day_detail(message: Message, state: FSMContext):
    user_id = message.from_user.id
    name = await active_name(user_id, state)

    if not name:
        return await prompt_choose_own_name(message, state)

    week_days = await get_user_week(state)
    if not week_days:
        return await answer_html(message, "Сначала открой неделю.", reply_markup=my_schedule_kb())

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

    async def _load():
        body = await schedule.get_day_schedule(
            name, target.day, target.month, target.year, target_role=role,
        )
        return await with_viewing_context(state, body)

    await loading_answer(
        message, f"⏳ Загружаю {day_label}...",
        _load(),
        reply_markup=week_kb(week_days),
    )


@router.message(F.text == "📋 Весь график")
@router.message(F.text == "📋 Выбрать месяц")
async def choose_month(message: Message):
    await answer_html(message, "📋 <b>Выбери месяц</b>", reply_markup=months_kb())


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
        return await answer_html(message, "Не могу определить месяц.", reply_markup=my_schedule_kb())

    role = await active_role(message.from_user.id, state)
    max_day = calendar.monthrange(year, month)[1]

    async def _load():
        body = await schedule.get_range_schedule(name, 1, max_day, month, year, target_role=role)
        return await with_viewing_context(state, body)

    await loading_answer(
        message, "⏳ Загружаю полный график...",
        _load(),
        reply_markup=my_schedule_kb(),
    )


@router.message(F.text == "👥 Кто сегодня")
async def who_today(message: Message):
    await loading_answer(
        message, "⏳ Проверяю, кто работает сегодня...",
        schedule.get_people(now_local().day, message.from_user.id),
        reply_markup=await main_kb_async(message.from_user.id),
    )


@router.message(F.text == "👥 Кто завтра")
async def who_tomorrow(message: Message):
    tomorrow_dt = now_local() + timedelta(days=1)
    await loading_answer(
        message, "⏳ Проверяю, кто работает завтра...",
        schedule.get_people(
            tomorrow_dt.day, message.from_user.id, tomorrow_dt.month, tomorrow_dt.year,
        ),
        reply_markup=await main_kb_async(message.from_user.id),
    )
