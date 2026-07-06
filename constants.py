import os

ROLE_RATE_ENV: dict[str, str] = {
    "Официант": "RATE_WAITER",
    "Хостес": "RATE_HOSTESS",
    "Бармен": "RATE_BARTENDER",
    "Кальянщик": "RATE_HOOKAH",
    "Менеджеры": "RATE_MANAGER",
    "Стажер": "RATE_INTERN",
}


def env_rates() -> dict[str, int]:
    return {
        role: int(os.getenv(env_key, 0))
        for role, env_key in ROLE_RATE_ENV.items()
    }


# Заполняется services.rates_service при старте.
RATES: dict[str, int] = env_rates()

SHIFT_HOURS: dict[tuple, float] = {
    ("morning", "weekday"): 12.5,   # Пн–Чт, Вс
    ("morning", "weekend"): 14.5,   # Пт, Сб
    ("evening", "weekday"): 10.0,   # Пн–Чт, Вс
    ("evening", "weekend"): 12.0,   # Пт, Сб
}

SHIFT_END_NOTIFY: dict[tuple, str] = {
    ("morning", "weekday"): "23:05",  # Пн–Чт, Вс
    ("morning", "weekend"): "01:05",  # Пт, Сб — уведомление на след. день
    ("evening", "weekday"): "02:05",  # Пн–Чт, Вс — уведомление на след. день
    ("evening", "weekend"): "04:05",  # Пт, Сб — уведомление на след. день
}

SHEET_GID_MAP = {
    (2026, 5, 1):  "1690889478",   # Май 1-15
    (2026, 5, 16): "1467004546",   # Май 16-31
    (2026, 6, 1):  "608196188",    # Июнь 1-15
    (2026, 6, 16): "496035797",   # Июнь 16-30
    (2026, 7, 1):  "2125046654",  # Июль 1-15
    # сюда добавляй новые листы: (год, месяц, день_начала): "gid"
}

