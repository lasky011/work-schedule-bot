"""Отправка сообщений пользователю из Mini App API."""

import asyncio
import logging

import requests

from app_config import BOT_TOKEN


def _send_sync(chat_id: int, text: str, reply_markup: dict | None = None) -> None:
    if not BOT_TOKEN:
        return
    try:
        payload = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        resp = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=10,
        )
        if not resp.ok:
            logging.warning("telegram_notify: %s %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logging.warning("telegram_notify failed: %s", e)


async def send_user_message(
    chat_id: int,
    text: str,
    reply_markup: dict | None = None,
) -> None:
    await asyncio.to_thread(_send_sync, chat_id, text, reply_markup)
