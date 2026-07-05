"""Уведомления администраторам через admin-бот."""

import asyncio
import logging

import requests

from app_config import ADMIN_BOT_TOKEN, ADMIN_IDS


def _send_admin_sync(chat_id: int, text: str) -> bool:
    if not ADMIN_BOT_TOKEN:
        logging.warning("admin_notify: ADMIN_BOT_TOKEN is missing")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{ADMIN_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        if not resp.ok:
            logging.warning("admin_notify: %s %s", resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as e:
        logging.warning("admin_notify failed chat_id=%s: %s", chat_id, e)
        return False


async def notify_admins(text: str) -> int:
    if not ADMIN_IDS:
        return 0
    sent = 0
    for admin_id in ADMIN_IDS:
        ok = await asyncio.to_thread(_send_admin_sync, admin_id, text)
        if ok:
            sent += 1
    return sent
