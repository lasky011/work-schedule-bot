import os

RATES: dict[str, int] = {
    "Официант":  int(os.getenv("RATE_WAITER", 0)),
    "Хостес":    int(os.getenv("RATE_HOSTESS", 0)),
    "Бармен":    int(os.getenv("RATE_BARTENDER", 0)),
    "Кальянщик": int(os.getenv("RATE_HOOKAH", 0)),
    "Менеджер":  int(os.getenv("RATE_MANAGER", 0)),
}

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
    # сюда добавляй новые листы: (год, месяц, день_начала): "gid"
}

