"""Inline-кнопки Mini App под уведомлениями."""

from urllib.parse import urlencode

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app_config import MINIAPP_URL


def miniapp_link(**params: str) -> str:
    if not MINIAPP_URL:
        return ""
    base = MINIAPP_URL.rstrip("/") + "/"
    if not params:
        return base
    return f"{base}?{urlencode(params)}"


def daily_notify_kb() -> InlineKeyboardMarkup | None:
    if not MINIAPP_URL:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👥 Кто сегодня на смене",
                    web_app=WebAppInfo(url=miniapp_link(view="team", day="today")),
                ),
            ],
        ],
    )


def hours_notify_kb(date_str: str) -> InlineKeyboardMarkup:
    if MINIAPP_URL:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⏱ Внести часы",
                        web_app=WebAppInfo(url=miniapp_link(view="hours", date=date_str)),
                    ),
                ],
            ],
        )
    from keyboards.inline_salary import shift_entry_kb

    return shift_entry_kb(date_str)


def miniapp_open_kb(view: str | None = None) -> InlineKeyboardMarkup | None:
    if not MINIAPP_URL:
        return None
    params = {"view": view} if view else {}
    url = miniapp_link(**params) if params else miniapp_link()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✨ Открыть TNG Alice", web_app=WebAppInfo(url=url))],
        ],
    )


def miniapp_broadcast_markup() -> dict | None:
    url = miniapp_link()
    if not url:
        return None
    return {
        "inline_keyboard": [
            [{"text": "✨ Открыть TNG Alice", "web_app": {"url": url}}],
        ],
    }


def schedule_change_reply_markup() -> dict | None:
    url = miniapp_link(view="schedule") if MINIAPP_URL else ""
    if not url:
        return None
    return {
        "inline_keyboard": [
            [{"text": "📅 Открыть график", "web_app": {"url": url}}],
        ],
    }
