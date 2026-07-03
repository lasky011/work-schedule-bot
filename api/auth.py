"""Проверка Telegram WebApp initData."""

import hashlib
import hmac
import json
from urllib.parse import parse_qsl


class InitDataError(ValueError):
    pass


def validate_init_data(init_data: str, bot_token: str) -> dict:
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
