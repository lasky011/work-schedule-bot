import os
import logging
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
SHEET_ID = os.getenv("SHEET_ID", "1bRuO870pDBf6O-kXJ1O342SmxmjZgpsiacM2aPOJm9Y")

APP_TIMEZONE_NAME = os.getenv("APP_TIMEZONE", "Europe/Moscow")
APP_TIMEZONE = ZoneInfo(APP_TIMEZONE_NAME)


def now_local():
    from datetime import datetime
    return datetime.now(APP_TIMEZONE)


def _parse_admin_ids(raw: str | None) -> set[int]:
    if not raw:
        return set()

    result = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue

        try:
            result.add(int(part))
        except ValueError:
            logging.warning("Некорректный ADMIN_IDS элемент: %s", part)

    return result


ADMIN_IDS = _parse_admin_ids(os.getenv("ADMIN_IDS"))


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def validate_required_env():
    required = {
        "BOT_TOKEN": BOT_TOKEN,
        "DATABASE_URL": DATABASE_URL,
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise SystemExit(f"❌ Не заданы обязательные переменные: {', '.join(missing)}")
