"""Fallback-хендлер для неизвестных сообщений (подключается последним)."""

from aiogram import F, Router
from aiogram.types import Message

from app_config import MINIAPP_URL
from keyboards import main_kb_async
from keyboards.inline_miniapp import miniapp_open_kb
from ui_utils import answer_html, with_loading

router = Router(name="fallback")

MINIAPP_REDIRECTS = {
    "📌 Мой график": ("график", "График теперь в TNG Alice"),
    "👀 Коллеги": ("people", "Коллеги — в TNG Alice"),
    "💰 Зарплата": ("salary", "Зарплата — в TNG Alice"),
    "🔔 Уведомления": ("settings", "Настройки — в TNG Alice"),
}


@router.message(F.text)
@with_loading("⏳ Обрабатываю...")
async def text_handler(message: Message):
    user_id = message.from_user.id
    text = (message.text or "").strip()

    if MINIAPP_URL and text in MINIAPP_REDIRECTS:
        view, hint = MINIAPP_REDIRECTS[text]
        kb = miniapp_open_kb(view=view) if view else miniapp_open_kb()
        await answer_html(
            message,
            f"{hint} ✨\n\nИли нажми кнопку меню внизу чата.",
            reply_markup=kb,
        )
        return

    await answer_html(
        message,
        "Используй кнопки ниже 👇\nГрафик и всё остальное — в TNG Alice (кнопка меню внизу чата).",
        reply_markup=await main_kb_async(user_id),
    )
