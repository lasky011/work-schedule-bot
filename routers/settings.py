"""Настройки: имя, отдел, уведомления."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from departments_manager import DEPARTMENTS, is_department_label, is_person_name
from fsm_context import (
    clear_colleague_view,
    clear_notification_state,
    get_compare_selected,
    get_viewing_colleague,
    pop_last_selected_dept,
    prompt_choose_own_name,
    reset_compare_mode,
    reset_modes,
    set_last_selected_dept,
)
from keyboards import (
    colleague_kb,
    colleague_names_kb,
    compare_names_kb,
    dep_kb,
    main_kb_async,
    notifications_kb,
    own_names_kb,
)
from repositories.users_repo import get_user, save_user
from states import CompareStates, NameFlowStates, NotificationStates
from message_format import onboarding_step
from ui_utils import answer_html, is_valid_time, with_loading

router = Router(name="settings")


@router.message(F.text.startswith("👤 "))
async def choose_own_name(message: Message, state: FSMContext):
    await clear_notification_state(state)
    await clear_colleague_view(state)
    await reset_compare_mode(state)
    await state.set_state(NameFlowStates.choosing_own_department)
    await answer_html(message, onboarding_step(1, 3, "<b>Шаг 1:</b> выбери подразделение"), reply_markup=dep_kb())


@router.message(F.text.func(is_department_label))
async def department_selected(message: Message, state: FSMContext):
    user_id = message.from_user.id
    department = message.text

    parts = department.split(" ", 1)
    dept_role = parts[1] if len(parts) == 2 else department
    await set_last_selected_dept(state, dept_role)

    current = await state.get_state()
    if current == NameFlowStates.choosing_compare_department.state:
        await state.set_state(CompareStates.selecting_people)
        await message.answer(
            "Выбери сотрудника для сравнения:",
            reply_markup=await compare_names_kb(
                department, user_id, await get_compare_selected(state),
            ),
        )
    elif current == NameFlowStates.choosing_colleague_department.state:
        await state.set_state(None)
        await answer_html(
            message,
            onboarding_step(2, 2, "<b>Шаг 2:</b> выбери коллегу"),
            reply_markup=await colleague_names_kb(department, user_id),
        )
    else:
        await state.set_state(NameFlowStates.choosing_own_name)
        await answer_html(
            message,
            onboarding_step(2, 3, "<b>Шаг 2:</b> выбери своё имя"),
            reply_markup=own_names_kb(department),
        )


@router.message(F.text.func(is_person_name))
@with_loading("⏳ Сохраняю...")
async def own_name_selected(message: Message, state: FSMContext):
    user_id = message.from_user.id

    user_role = await pop_last_selected_dept(state)
    if not user_role:
        for dept_label, names in DEPARTMENTS.items():
            if message.text in names:
                parts = dept_label.split(" ", 1)
                user_role = parts[1] if len(parts) == 2 else dept_label
                break

    await save_user(user_id, name=message.text, notify=0, notify_time='', role=user_role)
    from services.schedule_watch_service import reset_user_snapshot
    await reset_user_snapshot(user_id)
    await reset_modes(user_id, state)

    await answer_html(
        message,
        f"✅ <b>Готово!</b>\n\nТеперь ты — <b>{message.text}</b>",
        reply_markup=await main_kb_async(user_id),
    )


@router.message(F.text == "🔔 Уведомления")
@with_loading("⏳ Загружаю...")
async def notifications_menu(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if await get_viewing_colleague(state):
        return await message.answer(
            "Уведомления можно настраивать только для своего имени.\nНажми «⬅️ Вернуться к себе».",
            reply_markup=colleague_kb(),
        )

    user = await get_user(user_id)

    if not user or not user[1]:
        return await prompt_choose_own_name(message, state)

    status = "включены 🔔" if user[2] else "выключены 🔕"
    notify_time = user[3] or "не задано"

    await answer_html(
        message,
        f"🔔 <b>Настройки уведомлений</b>\n\n"
        f"Статус: <b>{status}</b>\n"
        f"Время: <code>{notify_time}</code>",
        reply_markup=notifications_kb(),
    )


@router.message(F.text == "🔔 Включить")
@with_loading("⏳ Сохраняю...")
async def notifications_on(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user = await get_user(user_id)

    if not user or not user[1]:
        return await prompt_choose_own_name(message, state)

    if not user[3]:
        await state.set_state(NotificationStates.waiting_for_time)
        return await message.answer("Сначала задай время уведомления. Например: 09:30")

    await save_user(user_id, notify=1)

    await message.answer(
        f"Уведомления включены 🔔\nВремя: {user[3]}",
        reply_markup=await main_kb_async(user_id),
    )


@router.message(F.text == "🔕 Выключить")
@with_loading("⏳ Сохраняю...")
async def notifications_off(message: Message, state: FSMContext):
    await save_user(message.from_user.id, notify=0)
    await clear_notification_state(state)
    await message.answer(
        "Уведомления выключены 🔕",
        reply_markup=await main_kb_async(message.from_user.id),
    )


@router.message(F.text == "✍️ Задать время")
@with_loading("⏳ Загружаю...")
async def ask_notification_time(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user = await get_user(user_id)

    if not user or not user[1]:
        return await prompt_choose_own_name(message, state)

    await state.set_state(NotificationStates.waiting_for_time)
    await message.answer("Напиши время уведомления в формате ЧЧ:ММ\n\nНапример: 09:30")


@router.message(NotificationStates.waiting_for_time, F.text)
async def save_notification_time(message: Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text.strip()

    if not is_valid_time(text):
        return await message.answer("Неверный формат. Напиши так: 09:30")

    await save_user(user_id, notify_time=text, notify=1)
    await state.clear()

    await message.answer(
        "Время уведомлений сохранено: " + text + "\nУведомления включены 🔔",
        reply_markup=await main_kb_async(user_id),
    )
