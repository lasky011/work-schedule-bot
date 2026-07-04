"""Старт и главное меню."""

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from fsm_context import reset_modes
from keyboards import dep_kb, main_kb_async
from message_format import welcome_card
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
        text = welcome_card(
            f", {user[1]}",
            "Открывай TNG Alice через кнопку меню внизу чата ✨",
        )
        await answer_html(message, text, reply_markup=await main_kb_async(user_id))
    else:
        await state.set_state(NameFlowStates.choosing_own_department)
        await answer_html(
            message,
            "Привет 👋\n\n"
            "Я бот расписания. Для начала выбери <b>подразделение</b>:",
            reply_markup=dep_kb(),
        )


@router.message(F.text == "🏠 Главное меню")
@with_loading("⏳ Загружаю...")
async def home(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await reset_modes(user_id, state)

    name = await get_user_name(user_id)
    greeting = f"Привет, <b>{name}</b> 👋" if name else "🏠 <b>Главное меню</b>"
    await answer_html(message, greeting, reply_markup=await main_kb_async(user_id))
