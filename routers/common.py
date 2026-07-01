"""Старт и главное меню."""

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from fsm_context import reset_modes
from keyboards import main_kb_async
from repositories.users_repo import get_user, get_user_name
from states import NameFlowStates
from ui_utils import with_loading

router = Router(name="common")

WELCOME_TEXT = (
    "Привет{name_part} 👋\n\n"
    "Я бот расписания — помогаю смотреть график и считать зарплату.\n\n"
    "📌 Мой график — сегодня, завтра, неделя или весь месяц\n"
    "👀 Коллеги — кто работает рядом, совпадение смен\n"
    "💰 Зарплата — примерный расчёт по ставке и учёт фактических часов\n"
    "🔔 Уведомления — о графике каждый день и напоминание внести часы\n\n"
    "{action}"
)


@router.message(CommandStart())
@with_loading("⏳ Загружаю...")
async def start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await reset_modes(user_id, state)

    user = await get_user(user_id)

    if user and user[1]:
        await message.answer(
            WELCOME_TEXT.format(
                name_part=f", {user[1]}",
                action="Выбери раздел 👇",
            ),
            reply_markup=await main_kb_async(user_id),
        )
    else:
        await message.answer(
            WELCOME_TEXT.format(
                name_part="",
                action="Для начала выбери своё имя — нажми 📌 Мой график.",
            ),
            reply_markup=await main_kb_async(user_id),
        )
        await state.set_state(NameFlowStates.choosing_own_department)


@router.message(F.text == "🏠 Главное меню")
@with_loading("⏳ Загружаю...")
async def home(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await reset_modes(user_id, state)

    name = await get_user_name(user_id)
    greeting = f"Привет, {name} 👋" if name else "🏠 Главное меню"
    await message.answer(greeting, reply_markup=await main_kb_async(user_id))
