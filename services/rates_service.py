"""Ставки ₽/час по ролям: БД + fallback на env."""

import asyncio
import logging

from constants import env_rates
from repositories.role_rates_repo import fetch_all, upsert

RATES_VERSION_KEY = "rates_version"

# role_key в БД → подпись в UI
ROLE_CATALOG: list[tuple[str, str]] = [
    ("Официант", "🍽 Официант"),
    ("Бармен", "🍸 Бармен"),
    ("Хостес", "🙋 Хостес"),
    ("Кальянщик", "💨 Кальян"),
    ("Менеджеры", "👔 Менеджеры"),
    ("Стажер", "🎓 Стажер"),
]

ROLE_ALIASES: dict[str, str] = {
    "Кальян": "Кальянщик",
    "Менеджер": "Менеджеры",
    "Официанты": "Официант",
    "Бармены": "Бармен",
}

# Общий dict — salary_service читает отсюда.
RATES: dict[str, int] = dict(env_rates())


def normalize_rate_role(role: str | None) -> str | None:
    if not role:
        return None
    text = str(role).replace("\xa0", " ").strip()
    if " " in text:
        text = text.split(" ", 1)[1]
    return ROLE_ALIASES.get(text, text)


def get_rate(role: str | None) -> int:
    key = normalize_rate_role(role)
    if not key:
        return 0
    return int(RATES.get(key, 0))


def role_label(role_key: str) -> str:
    for key, label in ROLE_CATALOG:
        if key == role_key:
            return label
    return role_key


def _apply_rates(rows: dict[str, int]) -> None:
    RATES.clear()
    RATES.update(rows)


def _seed_from_env() -> dict[str, int]:
    env = {k: v for k, v in env_rates().items() if v > 0}
    if not env:
        return dict(env_rates())
    for role_key, rate in env.items():
        try:
            _upsert_sync_env(role_key, rate)
        except Exception as e:
            logging.warning("rates seed %s failed: %s", role_key, e)
    return env


def _upsert_sync_env(role_key: str, rate: int) -> None:
    from repositories.role_rates_repo import _upsert_sync

    _upsert_sync(role_key, rate)


def load_from_db_sync(*, quiet: bool = False) -> int:
    from db import USE_POSTGRES
    from repositories.role_rates_repo import _fetch_all_sync

    if not USE_POSTGRES:
        _apply_rates(env_rates())
        return len(RATES)

    try:
        rows = _fetch_all_sync()
    except Exception as e:
        logging.warning("rates: не удалось загрузить из БД: %s", e)
        if not RATES:
            _apply_rates(env_rates())
        return len(RATES)

    if not rows:
        seeded = _seed_from_env()
        _apply_rates(seeded)
        if not quiet and any(seeded.values()):
            logging.info("rates: импортировано из env (%s ролей)", len(seeded))
        return len(RATES)

    before = dict(RATES)
    _apply_rates({role_key: rate for role_key, rate in rows})
    if not quiet or before != RATES:
        logging.info("rates: загружено %s ставок из БД", len(RATES))
    return len(RATES)


async def reload_from_db(*, quiet: bool = False) -> int:
    return await asyncio.to_thread(load_from_db_sync, quiet=quiet)


async def set_rate(role_key: str, rate: int) -> None:
    if rate < 0:
        raise ValueError("Ставка не может быть отрицательной")
    await upsert(role_key, rate)
    RATES[role_key] = rate


def format_rates_text() -> str:
    lines = ["💰 Ставки сотрудников (₽/час)\n"]
    for role_key, label in ROLE_CATALOG:
        value = RATES.get(role_key, 0)
        if value:
            lines.append(f"{label} — {value:,} ₽".replace(",", " "))
        else:
            lines.append(f"{label} — не задана")
    lines.append("\nНажми ✏️ у роли, чтобы изменить.")
    return "\n".join(lines)


_last_applied_rates_version = 0


async def bump_rates_signal() -> int:
    from repositories.bot_state_repo import bump_int

    return await bump_int(RATES_VERSION_KEY)


async def apply_pending_rates_signal() -> bool:
    from repositories.bot_state_repo import get_int

    global _last_applied_rates_version

    current = await get_int(RATES_VERSION_KEY, default=0)
    if current <= _last_applied_rates_version:
        return False

    await reload_from_db(quiet=True)
    _last_applied_rates_version = current
    logging.info("rates signal applied: v%s", current)
    return True
