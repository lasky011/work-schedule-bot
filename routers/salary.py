"""Роутер раздела «Зарплата»: расчёт, учёт часов, история смен."""

import calendar
import re
from datetime import timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram_calendar import SimpleCalendar, SimpleCalendarCallback

from app_config import now_local
from departments_manager import DEPT_EMOJIS
from fsm_context import (
    clear_shift_entry_state,
    finish_shift_entry,
    get_shift_entry,
    get_shift_history_month,
    get_shift_history_period,
    set_shift_entry,
    set_shift_history_month,
    set_shift_history_period,
)
from keyboards import (
    dep_kb,
    get_shift_history_months,
    salary_kb,
    salary_period_kb,
    salary_settings_delete_kb,
    salary_settings_kb,
    shift_date_kb,
    shift_history_actions_kb,
    shift_history_delete_kb,
    shift_history_month_kb,
    shift_history_period_kb,
    shift_hours_kb,
)
from repositories.shifts_repo import delete_shift, get_shift_for_date, get_shifts_for_month, save_shift
from repositories.users_repo import get_user, save_user
from services import salary_service
from states import ShiftEntryStates, ShiftHistoryStates
from ui_utils import fmt_hours, with_loading

router = Router(name="salary")


@router.message(F.text == "💰 Зарплата")
@with_loading("⏳ Загружаю...")
async def salary_menu(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    if not user or not user[1]:
        return await message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())
    track_hours = user[5] if user and len(user) > 5 else 0
    role = user[4] if user and len(user) > 4 else None
    role_line = f"\n{DEPT_EMOJIS.get(role, role)}" if role else ""
    await message.answer(f"💰 Зарплата\n{user[1]}{role_line}", reply_markup=salary_kb(track_hours or 0))


@router.message(F.text == "📊 Примерная зарплата")
@with_loading("⏳ Загружаю...")
async def salary_stats_choose_period(message: Message):
    user = await get_user(message.from_user.id)
    if not user or not user[1]:
        return await message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())
    await message.answer("Выбери период:", reply_markup=salary_period_kb())


@router.message(F.text == "📅 Текущий период")
async def salary_current_period(message: Message):
    now = now_local()
    month, year = now.month, now.year
    if now.day <= 15:
        period_start, period_end = 1, 15
    else:
        period_end = calendar.monthrange(year, month)[1]
        period_start = 16

    user = await get_user(message.from_user.id)
    track_hours = user[5] if user and len(user) > 5 else 0
    text = await salary_service.build_salary_stats_text(
        message.from_user.id, user, year, month, period_start, period_end,
    )
    await message.answer(text, reply_markup=salary_kb(track_hours or 0))


@router.message(F.text.regexp(r"^(1-15|16-\d+) [А-Яа-я]+$"))
async def salary_period_selected(message: Message):
    parsed = salary_service.parse_salary_period_button(message.text, now_local())
    if not parsed:
        return await message.answer("Не удалось определить период.", reply_markup=salary_period_kb())

    year, month_num, period_start, period_end = parsed
    user = await get_user(message.from_user.id)
    track_hours = user[5] if user and len(user) > 5 else 0
    text = await salary_service.build_salary_stats_text(
        message.from_user.id, user, year, month_num, period_start, period_end,
    )
    await message.answer(text, reply_markup=salary_kb(track_hours or 0))


@router.message(F.text == "⚙️ Настройки учёта")
@with_loading("⏳ Загружаю...")
async def salary_settings(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    track_hours = user[5] if user and len(user) > 5 else 0
    notify_hours = user[6] if user and len(user) > 6 else 0
    notify_info = ""
    if notify_hours:
        notify_info = (
            "\n\n🕐 Расписание уведомлений:\n"
            "  Утро (Пн–Чт, Вс) → 23:05\n"
            "  Утро (Пт, Сб) → 01:05 (след. день)\n"
            "  Вечер (Пн–Чт, Вс) → 02:05 (след. день)\n"
            "  Вечер (Пт, Сб) → 04:05 (след. день)"
        )
    await message.answer(
        "⚙️ Настройки учёта часов:" + notify_info,
        reply_markup=salary_settings_kb(track_hours or 0, notify_hours or 0),
    )


@router.message(F.text.in_({"⬜ Включить учёт часов", "🔴 Выключить учёт часов"}))
@with_loading("⏳ Сохраняю...")
async def toggle_track_hours(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    track_hours = user[5] if user and len(user) > 5 else 0
    notify_hours = user[6] if user and len(user) > 6 else 0
    new_val = 0 if track_hours else 1
    await save_user(user_id, track_hours=new_val)
    text = "✅ Учёт часов включён! Теперь можешь вносить смены." if new_val else "⬜ Учёт часов выключен."
    await message.answer(text, reply_markup=salary_settings_kb(new_val, notify_hours or 0))


@router.message(F.text.in_({"🔔 Уведомление включено", "🔕 Уведомление выключено"}))
@with_loading("⏳ Сохраняю...")
async def toggle_notify_hours(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    track_hours = user[5] if user and len(user) > 5 else 0
    notify_hours = user[6] if user and len(user) > 6 else 0
    new_val = 0 if notify_hours else 1
    await save_user(user_id, notify_hours=new_val)
    if new_val:
        schedule_text = (
            "🔔 Уведомление включено.\n\n"
            "Буду напоминать внести часы автоматически:\n"
            "• Утро (Пн–Чт, Вс) — в 23:05\n"
            "• Утро (Пт, Сб) — в 01:05 (след. день)\n"
            "• Вечер (Пн–Чт, Вс) — в 02:05 (след. день)\n"
            "• Вечер (Пт, Сб) — в 04:05 (след. день)"
        )
        await message.answer(schedule_text, reply_markup=salary_settings_kb(track_hours or 0, new_val))
    else:
        await message.answer("🔕 Уведомление выключено.", reply_markup=salary_settings_kb(track_hours or 0, new_val))


@router.message(F.text == "🗑 Удалить смену из истории")
@with_loading("⏳ Загружаю...")
async def delete_shift_choose(message: Message):
    user_id = message.from_user.id
    now = now_local()
    shifts = await get_shifts_for_month(user_id, now.year, now.month)
    if not shifts:
        user = await get_user(user_id)
        track_hours = user[5] if user and len(user) > 5 else 0
        notify_hours = user[6] if user and len(user) > 6 else 0
        return await message.answer(
            "Нет внесённых смен за этот месяц.",
            reply_markup=salary_settings_kb(track_hours or 0, notify_hours or 0),
        )
    await message.answer(
        "Выбери смену для удаления:",
        reply_markup=salary_settings_delete_kb(shifts),
    )


@router.message(F.text.regexp(r"^🗑 \d{4}-\d{2}-\d{2}"))
@with_loading("⏳ Удаляю...")
async def delete_shift_confirm(message: Message):
    user_id = message.from_user.id
    date_str = message.text.replace("🗑 ", "").split(" — ")[0].strip()
    deleted = await delete_shift(user_id, date_str)
    user = await get_user(user_id)
    track_hours = user[5] if user and len(user) > 5 else 0
    notify_hours = user[6] if user and len(user) > 6 else 0
    if deleted:
        await message.answer(
            "✅ Смена за " + date_str + " удалена.",
            reply_markup=salary_settings_kb(track_hours or 0, notify_hours or 0),
        )
    else:
        await message.answer(
            "Смена не найдена.",
            reply_markup=salary_settings_kb(track_hours or 0, notify_hours or 0),
        )


@router.message(F.text == "⬅️ Назад к настройкам")
@with_loading("⏳ Загружаю...")
async def back_to_settings(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await clear_shift_entry_state(state)
    user = await get_user(user_id)
    track_hours = user[5] if user and len(user) > 5 else 0
    notify_hours = user[6] if user and len(user) > 6 else 0
    await message.answer(
        "⚙️ Настройки учёта часов:",
        reply_markup=salary_settings_kb(track_hours or 0, notify_hours or 0),
    )


@router.message(F.text == "⬅️ Назад к зарплате")
@with_loading("⏳ Загружаю...")
async def back_to_salary(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await clear_shift_entry_state(state)
    user = await get_user(user_id)
    track_hours = user[5] if user and len(user) > 5 else 0
    await message.answer("💰 Зарплата", reply_markup=salary_kb(track_hours or 0))


@router.message(F.text == "⏱ Внести смену")
async def enter_shift_start(message: Message):
    now = now_local()
    await message.answer(
        "Выбери дату смены:",
        reply_markup=await SimpleCalendar(
            cancel_btn="Отмена", today_btn="Сегодня",
        ).start_calendar(year=now.year, month=now.month),
    )


@router.callback_query(SimpleCalendarCallback.filter())
@with_loading("⏳ Проверяю график...")
async def process_calendar(callback: CallbackQuery, callback_data: SimpleCalendarCallback, state: FSMContext):
    user_id = callback.from_user.id
    user = await get_user(user_id)

    selected, dt = await SimpleCalendar(
        cancel_btn="Отмена", today_btn="Сегодня",
    ).process_selection(callback, callback_data)
    if not selected:
        return

    if not user or not user[1]:
        await callback.message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())
        return

    name = user[1]
    role = user[4] if len(user) > 4 else None
    date_str = dt.strftime("%Y-%m-%d")
    existing = await get_shift_for_date(user_id, date_str)
    shift_type, standard_hours = await salary_service.lookup_shift_for_date(name, role, dt)

    await set_shift_entry(state, {
        "date": date_str,
        "shift_type": shift_type,
        "standard_hours": standard_hours,
    })

    await callback.message.answer(
        salary_service.format_shift_entry_prompt(dt, shift_type, standard_hours, existing),
        reply_markup=shift_hours_kb(standard_hours),
    )


@router.message(F.text.in_({"📥 Сегодня", "📥 Вчера"}))
@with_loading("⏳ Проверяю график...")
async def shift_date_selected(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user = await get_user(user_id)
    if not user or not user[1]:
        return await message.answer("Сначала выбери своё имя.", reply_markup=dep_kb())

    name = user[1]
    role = user[4] if len(user) > 4 else None
    now = now_local()
    dt = now if message.text == "📥 Сегодня" else now - timedelta(days=1)
    date_str = dt.strftime("%Y-%m-%d")
    existing = await get_shift_for_date(user_id, date_str)
    shift_type, standard_hours = await salary_service.lookup_shift_for_date(name, role, dt)

    await set_shift_entry(state, {
        "date": date_str,
        "shift_type": shift_type,
        "standard_hours": standard_hours,
    })

    await message.answer(
        salary_service.format_shift_entry_prompt(dt, shift_type, standard_hours, existing),
        reply_markup=shift_hours_kb(standard_hours),
    )


@router.message(ShiftEntryStates.choosing_hours, F.text.startswith("✅ Стандартная ("))
@with_loading("⏳ Сохраняю...")
async def shift_standard_selected(message: Message, state: FSMContext):
    user_id = message.from_user.id
    entry = await get_shift_entry(state)
    if not entry:
        return await message.answer("Сначала выбери дату.", reply_markup=shift_date_kb())
    await save_shift(
        user_id=user_id,
        date=entry["date"],
        hours=entry["standard_hours"],
        shift_type=entry.get("shift_type"),
        is_standard=True,
    )
    await finish_shift_entry(state)
    user = await get_user(user_id)
    track_hours = user[5] if user and len(user) > 5 else 0
    await message.answer(
        "✅ Смена внесена: " + fmt_hours(entry["standard_hours"]) + " ч за " + entry["date"],
        reply_markup=salary_kb(track_hours or 0),
    )


@router.message(ShiftEntryStates.choosing_hours, F.text == "✍️ Указать своё время")
async def shift_custom_hours(message: Message, state: FSMContext):
    if not await get_shift_entry(state):
        return await message.answer("Сначала выбери дату.", reply_markup=shift_date_kb())
    await state.set_state(ShiftEntryStates.waiting_custom_hours)
    await message.answer("Напиши количество часов, например: 11.5")


@router.message(ShiftEntryStates.waiting_custom_hours, F.text)
async def save_custom_shift_hours(message: Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text.strip()
    try:
        hours = float(text.replace(",", "."))
        if hours <= 0 or hours > 24:
            raise ValueError
    except ValueError:
        return await message.answer("Напиши число, например: 11.5")

    entry = await get_shift_entry(state)
    if not entry:
        await finish_shift_entry(state)
        return await message.answer("Что-то пошло не так. Начни заново.", reply_markup=shift_date_kb())

    await save_shift(
        user_id=user_id,
        date=entry["date"],
        hours=hours,
        shift_type=entry.get("shift_type"),
        is_standard=False,
    )
    await finish_shift_entry(state)
    user = await get_user(user_id)
    track_hours = user[5] if user and len(user) > 5 else 0
    await message.answer(
        "✅ Смена внесена: " + fmt_hours(hours) + " ч за " + entry["date"],
        reply_markup=salary_kb(track_hours or 0),
    )


@router.message(F.text == "📋 История смен")
async def shift_history(message: Message, state: FSMContext):
    months = get_shift_history_months()
    if not months:
        return await message.answer(
            "📋 Нет доступных месяцев для истории смен. Добавь gid в SHEET_GID_MAP.",
            reply_markup=salary_kb(),
        )

    await state.set_state(ShiftHistoryStates.selecting_month)
    await message.answer(
        "📅 Выбери месяц истории смен:",
        reply_markup=shift_history_month_kb(),
    )


@router.message(ShiftHistoryStates.selecting_month, F.text.regexp(r"^🧾 Месяц: .+ \d{4}$"))
async def shift_history_month_selected(message: Message, state: FSMContext):
    parsed = salary_service.parse_shift_history_month_button(message.text)
    if not parsed:
        return

    year, month = parsed
    await set_shift_history_month(state, year, month)

    await message.answer(
        "📋 Выбери период истории смен:",
        reply_markup=shift_history_period_kb(month, year),
    )


@router.message(F.text == "⬅️ Назад к выбору месяца")
async def shift_history_back_to_month(message: Message, state: FSMContext):
    await state.set_state(ShiftHistoryStates.selecting_month)
    await message.answer(
        "📅 Выбери месяц истории смен:",
        reply_markup=shift_history_month_kb(),
    )


@router.message(F.text == "⬅️ Назад к выбору периода")
async def shift_history_back_to_period(message: Message, state: FSMContext):
    selected_month = await get_shift_history_month(state)

    if not selected_month:
        period = await get_shift_history_period(state)
        if period:
            year, month, _start_day, _end_day = period
            selected_month = (year, month)

    if not selected_month:
        await state.set_state(ShiftHistoryStates.selecting_month)
        return await message.answer(
            "📅 Выбери месяц истории смен:",
            reply_markup=shift_history_month_kb(),
        )

    year, month = selected_month
    await state.set_state(ShiftHistoryStates.selecting_period)
    await message.answer(
        "📋 Выбери период истории смен:",
        reply_markup=shift_history_period_kb(month, year),
    )


@router.message(ShiftHistoryStates.selecting_period, F.text.regexp(r"^🧾 Период: \d+–\d+ .+ \d{4}$"))
async def shift_history_period_selected(message: Message, state: FSMContext):
    parsed = salary_service.parse_shift_history_period_button(message.text)
    if not parsed:
        return

    year, month, start_day, end_day = parsed
    user_id = message.from_user.id

    await set_shift_history_period(state, year, month, start_day, end_day)
    text = await salary_service.build_shift_history_text(user_id, year, month, start_day, end_day)
    await message.answer(text, reply_markup=shift_history_actions_kb())


@router.message(F.text == "🗑 Удалить смену из этого периода")
async def shift_history_delete_choose(message: Message, state: FSMContext):
    user_id = message.from_user.id
    period = await get_shift_history_period(state)

    if not period:
        return await message.answer(
            "Сначала выбери период истории смен.",
            reply_markup=shift_history_month_kb(),
        )

    year, month, start_day, end_day = period
    shifts = await salary_service.get_shift_history_period_shifts(
        user_id, year, month, start_day, end_day,
    )

    if not shifts:
        return await message.answer(
            "В этом периоде нет внесённых смен.",
            reply_markup=shift_history_actions_kb(),
        )

    await message.answer(
        "🗑 Выбери смену для удаления:",
        reply_markup=shift_history_delete_kb(shifts),
    )


@router.message(F.text == "⬅️ Назад к истории")
async def shift_history_back_to_selected_period(message: Message, state: FSMContext):
    user_id = message.from_user.id
    period = await get_shift_history_period(state)

    if not period:
        return await message.answer(
            "📅 Выбери месяц истории смен:",
            reply_markup=shift_history_month_kb(),
        )

    year, month, start_day, end_day = period
    text = await salary_service.build_shift_history_text(user_id, year, month, start_day, end_day)
    await message.answer(text, reply_markup=shift_history_actions_kb())


@router.message(F.text.regexp(r"^❌ \d{4}-\d{2}-\d{2} — .+"))
async def shift_history_delete_confirm(message: Message, state: FSMContext):
    user_id = message.from_user.id

    m = re.match(r"^❌ (\d{4}-\d{2}-\d{2}) — .+", message.text)
    if not m:
        return

    date_str = m.group(1)
    deleted = await delete_shift(user_id, date_str)

    if deleted:
        await message.answer(f"✅ Смена {date_str} удалена.")
    else:
        await message.answer(f"⚠️ Смена {date_str} не найдена или уже удалена.")

    period = await get_shift_history_period(state)
    if period:
        year, month, start_day, end_day = period
        text = await salary_service.build_shift_history_text(user_id, year, month, start_day, end_day)
        await message.answer(text, reply_markup=shift_history_actions_kb())
    else:
        await message.answer("📋 История смен", reply_markup=shift_history_month_kb())
