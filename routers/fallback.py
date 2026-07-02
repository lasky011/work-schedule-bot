"""Fallback-хендлер для неизвестных сообщений (подключается последним)."""

from aiogram import F, Router
from aiogram.types import Message

from keyboards import main_kb_async
from ui_utils import answer_html, with_loading

router = Router(name="fallback")


@router.message(F.text)
@with_loading("⏳ Обрабатываю...")
async def text_handler(message: Message):
    user_id = message.from_user.id
    await answer_html(
        message,
        "Используй кнопки ниже 👇",
        reply_markup=await main_kb_async(user_id),
    )
