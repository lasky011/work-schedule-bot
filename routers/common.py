"""Старт и главное меню."""

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from fsm_context import reset_modes
from keyboards import main_kb_async
from message_format import onboarding_step, welcome_card
from repositories.users_repo import get_user, get_user_name
from states import NameFlowStates
from ui_utils import answer_html, with_loading

router = Router(name="common")


@router.message(CommandStart())
@with_loading("⏳ Загружаю...")
async def start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await reset_modes(user_id, state)

    user = await get_user(user_id)

    if user and user[1]:
        text = welcome_card(f", {user[1]}", "Выбери раздел 👇")
        await answer_html(message, text, reply_markup=await main_kb_async(user_id))
    else:
        text = welcome_card("", "Для начала пройди короткую настройку 👇")
        await answer_html(message, text, reply_markup=await main_kb_async(user_id))
        await state.set_state(NameFlowStates.choosing_own_department)
        await answer_html(
            message,
            onboarding_step(1, 3, "<b>Шаг 1:</b> выбери своё подразделение"),
            reply_markup=await main_kb_async(user_id),
        )


@router.message(F.text == "🏠 Главное меню")
@with_loading("⏳ Загружаю...")
async def home(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await reset_modes(user_id, state)

    name = await get_user_name(user_id)
    greeting = f"Привет, <b>{name}</b> 👋" if name else "🏠 <b>Главное меню</b>"
    await answer_html(message, greeting, reply_markup=await main_kb_async(user_id))
