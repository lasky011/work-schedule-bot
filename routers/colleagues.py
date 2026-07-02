"""Роутер коллег и сравнения графиков."""

import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from fsm_context import (
    add_compare_selected_name,
    clear_colleague_view,
    clear_notification_state,
    get_compare_selected,
    get_viewing_colleague,
    get_viewing_colleague_role,
    is_comparing,
    pop_last_selected_dept,
    reset_compare_mode,
    selected_compare_text,
    set_colleague_view,
    set_compare_period,
    set_compare_selected,
    set_compare_selected_roles,
)
from keyboards import (
    compare_kb,
    compare_names_kb,
    compare_period_kb,
    dep_kb,
    get_available_periods,
    main_kb_async,
    colleague_kb,
    colleague_names_kb,
)
from repositories.users_repo import get_user_name
from departments_manager import role_display_label
from services import compare_service
from states import CompareStates, NameFlowStates
from message_format import context_banner
from ui_utils import answer_html, loading_answer, month_label, with_loading

router = Router(name="colleagues")


@router.message(F.text == "⬅️ Вернуться к себе")
@with_loading("⏳ Загружаю...")
async def back_to_self(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await clear_colleague_view(state)
    await reset_compare_mode(state)

    name = await get_user_name(user_id) or "не выбрано"
    await answer_html(
        message,
        f"👤 <b>Твой график</b> — {name}",
        reply_markup=await main_kb_async(user_id),
    )


@router.message(F.text == "⬅️ Назад к коллеге")
async def back_to_colleague(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if await state.get_state() in {
        CompareStates.selecting_period.state,
        NameFlowStates.choosing_compare_department.state,
    }:
        await state.set_state(CompareStates.selecting_people)

    colleague_name = await get_viewing_colleague(state)
    if not colleague_name:
        return await message.answer("Коллега не выбран.", reply_markup=await main_kb_async(user_id))

    role = await get_viewing_colleague_role(state)
    role_label = role_display_label(role) if role else None
    banner = context_banner(colleague_name, role_label)
    await answer_html(message, banner, reply_markup=colleague_kb())


@router.message(F.text == "⬅️ Назад к сравнению")
async def back_to_compare(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await state.set_state(CompareStates.selecting_people)
    await answer_html(
        message,
        "🤝 <b>Сравнение графиков</b>\n\n" + await selected_compare_text(state),
        reply_markup=compare_kb(),
    )


@router.message(F.text == "👀 Коллеги")
async def choose_colleague_department(message: Message, state: FSMContext):
    await clear_notification_state(state)
    await reset_compare_mode(state)
    await state.set_state(NameFlowStates.choosing_colleague_department)
    await answer_html(message, "👀 <b>Коллеги</b>\n\nВыбери подразделение:", reply_markup=dep_kb())


@router.message(F.text == "➕ Добавить сотрудника")
async def add_compare_person(message: Message, state: FSMContext):
    await state.set_state(NameFlowStates.choosing_compare_department)
    await message.answer("Выбери подразделение сотрудника:", reply_markup=dep_kb())


@router.message(F.text.startswith("👀 "))
async def colleague_selected(message: Message, state: FSMContext):
    colleague_name = message.text.replace("👀 ", "").strip()

    role = await pop_last_selected_dept(state)
    await set_colleague_view(state, colleague_name, role)
    await state.set_state(None)
    await set_compare_selected(state, {colleague_name})
    await set_compare_selected_roles(state, {colleague_name: role} if role else {})

    role_label = role_display_label(role) if role else None
    banner = context_banner(colleague_name, role_label)
    await answer_html(message, banner, reply_markup=colleague_kb())


@router.message(F.text.startswith("➕ "))
@with_loading("⏳ Загружаю...")
async def compare_person_selected(message: Message, state: FSMContext):
    user_id = message.from_user.id
    name = message.text.replace("➕ ", "").strip()
    my_name = await get_user_name(user_id)

    if name == my_name:
        return await message.answer("Себя добавлять не нужно — ты уже участвуешь в сравнении.")

    role = await pop_last_selected_dept(state)
    await add_compare_selected_name(state, name, role)

    await message.answer(
        f"Добавил: {name}\n\n" + await selected_compare_text(state),
        reply_markup=compare_kb(),
    )


@router.message(
    (F.text.startswith("✅ "))
    & (F.text != "✅ Посчитать совпадения")
    & (~F.text.startswith("✅ Стандартная ("))
)
async def compare_person_already_selected(message: Message, state: FSMContext):
    name = message.text.replace("✅ ", "").strip()
    await message.answer(
        f"{name} уже выбран.\n\n" + await selected_compare_text(state),
        reply_markup=compare_kb(),
    )


@router.message(F.text == "🤝 Совпадения")
async def compare_menu(message: Message, state: FSMContext):
    user_id = message.from_user.id
    colleague_name = await get_viewing_colleague(state)

    if not colleague_name:
        return await message.answer(
            "Сначала выбери коллегу через раздел «👀 Коллеги».",
            reply_markup=await main_kb_async(user_id),
        )

    await state.set_state(CompareStates.selecting_people)
    selected = await get_compare_selected(state)
    if colleague_name not in selected:
        role = await get_viewing_colleague_role(state)
        await add_compare_selected_name(state, colleague_name, role)

    await answer_html(
        message,
        "🤝 <b>Сравнение графиков</b>\n\n" + await selected_compare_text(state),
        reply_markup=compare_kb(),
    )


@router.message(F.text == "✅ Посчитать совпадения")
async def ask_compare_period(message: Message, state: FSMContext):
    await state.set_state(CompareStates.selecting_period)

    selected = await get_compare_selected(state)
    if not selected:
        return await message.answer(
            "Добавь хотя бы одного сотрудника для сравнения.",
            reply_markup=compare_kb(),
        )

    periods = get_available_periods()
    if not periods:
        return await message.answer(
            "❌ Нет доступных актуальных периодов. Попроси админа добавить gid через /add_period.",
            reply_markup=compare_kb(),
        )

    await message.answer(
        "📅 Выбери период для сравнения:",
        reply_markup=compare_period_kb(),
    )


@router.message(F.text.regexp(r"^📅 \d+–\d+ .+ \d{4}$"))
async def handle_compare_period_select(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if not await is_comparing(state):
        return

    m = re.match(r"^📅 (\d+)–(\d+) (.+) (\d{4})$", message.text)
    if not m:
        return

    start_day = int(m.group(1))
    end_day = int(m.group(2))
    month_name = m.group(3).strip()
    year = int(m.group(4))

    matched = None
    for period in get_available_periods():
        p_year, p_month, p_start, p_end = period
        if (
            p_year == year
            and p_start == start_day
            and p_end == end_day
            and month_label(p_month) == month_name
        ):
            matched = period
            break

    if not matched:
        return await message.answer(
            "❌ Период не найден или уже не актуален.",
            reply_markup=compare_period_kb(),
        )

    await set_compare_period(state, matched)
    await loading_answer(
        message,
        "⏳ Считаю совпадения...",
        compare_service.compare_multiple(user_id, state),
        reply_markup=compare_kb(),
    )


@router.message(F.text == "🗑 Очистить список")
async def clear_compare(message: Message, state: FSMContext):
    colleague_name = await get_viewing_colleague(state)

    if colleague_name:
        role = await get_viewing_colleague_role(state)
        await set_compare_selected(state, {colleague_name})
        await set_compare_selected_roles(state, {colleague_name: role} if role else {})
    else:
        await set_compare_selected(state, set())
        await set_compare_selected_roles(state, {})

    await message.answer(
        "Выбранные сотрудники очищены.\n\n" + await selected_compare_text(state),
        reply_markup=compare_kb(),
    )
