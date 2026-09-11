"""Отправка сообщений пользователю из Mini App API / основного бота."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import requests

from app_config import BOT_TOKEN, NOTIFY_DRY_RUN


@dataclass(frozen=True)
class SendResult:
    ok: bool
    error: str | None = None
    dry_run: bool = False


def _telegram_error_text(resp: requests.Response) -> str:
    try:
        data = resp.json()
        desc = data.get("description")
        if desc:
            return str(desc)
    except Exception:
        pass
    return (resp.text or f"HTTP {resp.status_code}")[:200]


def _send_sync(
    chat_id: int,
    text: str,
    reply_markup: dict | None = None,
    parse_mode: str | None = None,
) -> SendResult:
    if NOTIFY_DRY_RUN:
        logging.info(
            "telegram_notify DRY_RUN skip chat_id=%s len=%s",
            chat_id, len(text or ""),
        )
        return SendResult(ok=True, dry_run=True)

    if not BOT_TOKEN:
        logging.warning("telegram_notify: BOT_TOKEN is missing")
        return SendResult(ok=False, error="BOT_TOKEN missing")
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
            err = _telegram_error_text(resp)
            logging.warning("telegram_notify: %s %s", resp.status_code, err)
            return SendResult(ok=False, error=err)
        return SendResult(ok=True)
    except Exception as e:
        logging.warning("telegram_notify failed: %s", e)
        return SendResult(ok=False, error=str(e))


async def send_user_message_result(
    chat_id: int,
    text: str,
    reply_markup: dict | None = None,
    parse_mode: str | None = None,
) -> SendResult:
    return await asyncio.to_thread(
        _send_sync, chat_id, text, reply_markup, parse_mode,
    )


async def send_user_message(
    chat_id: int,
    text: str,
    reply_markup: dict | None = None,
    parse_mode: str | None = None,
) -> bool:
    result = await send_user_message_result(
        chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode,
    )
    return result.ok
