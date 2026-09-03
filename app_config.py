import os
import logging
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN")
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


def _parse_name_list(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


# Личный график управляющего не из Google Sheets. Официант «Владислав» — другой человек.
SUPERVISOR_NAMES = _parse_name_list(os.getenv("SUPERVISOR_NAMES")) or {"Владислав Байкалов"}


def is_supervisor_name(name: str | None) -> bool:
    return bool(name) and str(name).strip() in SUPERVISOR_NAMES


def _parse_listen_port(raw: str | None, fallback: int = 8080) -> int:
    try:
        port = int((raw or "").strip() or fallback)
    except ValueError:
        logging.warning("Некорректный порт %r, используем %s", raw, fallback)
        return fallback
    if not 1 <= port <= 65535:
        logging.warning("Порт %s вне 1–65535, используем %s", port, fallback)
        return fallback
    return port


MINIAPP_ENABLED = os.getenv("MINIAPP_ENABLED", "").lower() in ("1", "true", "yes")
MINIAPP_PORT = _parse_listen_port(os.getenv("MINIAPP_PORT") or os.getenv("PORT"))
MINIAPP_URL = (os.getenv("MINIAPP_URL") or "").rstrip("/")

# Как часто prod/test подтягивают gid из sheet_periods (секунды).
SHEET_PERIODS_REFRESH_SECONDS = int(os.getenv("SHEET_PERIODS_REFRESH_SECONDS", "300"))


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


def validate_admin_env():
    token = os.getenv("ADMIN_BOT_TOKEN")
    db_url = os.getenv("DATABASE_URL")
    admin_ids = _parse_admin_ids(os.getenv("ADMIN_IDS"))
    missing = []
    if not token:
        missing.append("ADMIN_BOT_TOKEN")
    if not db_url:
        missing.append("DATABASE_URL")
    if missing:
        raise SystemExit(f"❌ Не заданы обязательные переменные: {', '.join(missing)}")
    if not admin_ids:
        raise SystemExit("❌ ADMIN_IDS пуст — admin-бот не сможет авторизовать никого")
