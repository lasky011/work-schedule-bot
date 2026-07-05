"""Отправка сообщений пользователю из Mini App API."""

import asyncio
import logging

import requests

from app_config import BOT_TOKEN


def _send_sync(
    chat_id: int,
    text: str,
    reply_markup: dict | None = None,
    parse_mode: str | None = None,
) -> bool:
    if not BOT_TOKEN:
        logging.warning("telegram_notify: BOT_TOKEN is missing")
        return False
    try:
        payload = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if parse_mode:
            payload["parse_mode"] = parse_mode
        resp = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=10,
        )
        if not resp.ok:
            logging.warning("telegram_notify: %s %s", resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as e:
        logging.warning("telegram_notify failed: %s", e)
        return False


async def send_user_message(
    chat_id: int,
    text: str,
    reply_markup: dict | None = None,
    parse_mode: str | None = None,
) -> bool:
    return await asyncio.to_thread(_send_sync, chat_id, text, reply_markup, parse_mode)
