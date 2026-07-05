"""Проверка Telegram WebApp initData."""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


class InitDataError(ValueError):
    pass


DEFAULT_INIT_DATA_TTL_SECONDS = 24 * 60 * 60
DEFAULT_AUTH_DATE_FUTURE_SKEW_SECONDS = 60


def _parse_auth_date(parsed: dict) -> int:
    auth_date_raw = parsed.get("auth_date")
    if auth_date_raw is None:
        raise InitDataError("Нет auth_date")
    try:
        auth_date = int(str(auth_date_raw).strip())
    except (TypeError, ValueError) as e:
        raise InitDataError("Некорректный auth_date") from e
    if auth_date <= 0:
        raise InitDataError("Некорректный auth_date")
    return auth_date


def validate_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = DEFAULT_INIT_DATA_TTL_SECONDS,
    future_skew_seconds: int = DEFAULT_AUTH_DATE_FUTURE_SKEW_SECONDS,
    now_ts: int | None = None,
) -> dict:
    if not init_data or not bot_token:
        raise InitDataError("Нет данных авторизации")

    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise InitDataError("Нет hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if calculated != received_hash:
        raise InitDataError("Неверная подпись")

    auth_date = _parse_auth_date(parsed)
    current_ts = int(time.time()) if now_ts is None else int(now_ts)
    if auth_date > current_ts + future_skew_seconds:
        raise InitDataError("auth_date из будущего")
    if auth_date < current_ts - max_age_seconds:
        raise InitDataError("auth_date устарел")

    user_raw = parsed.get("user")
    if not user_raw:
        raise InitDataError("Нет пользователя")

    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError as e:
        raise InitDataError("Некорректный user") from e

    user_id = user.get("id")
    if not user_id:
        raise InitDataError("Нет user id")

    return {"user_id": int(user_id), "user": user}
