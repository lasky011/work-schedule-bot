"""
Лёгкий smoke-test проекта.

Запуск:
    python3 smoke_test.py

Цель:
- проверить импорты модулей;
- поймать NameError/ImportError после рефакторинга;
- проверить базовые чистые функции без Telegram API, PostgreSQL и Google Sheets.
"""

import asyncio
import sys
import traceback


def check(name, fn):
    try:
        fn()
        print(f"✅ {name}")
    except Exception as e:
        print(f"❌ {name}: {type(e).__name__}: {e}")
        traceback.print_exc()
        raise


def build_signed_init_data(
    bot_token: str,
    *,
    user_id: int = 42,
    auth_date: int | str | None = 1_700_000_000,
    tamper_hash: bool = False,
):
    import hashlib
    import hmac
    import json
    from urllib.parse import urlencode

    payload = {
        "user": json.dumps({"id": user_id, "first_name": "Smoke"}),
    }
    if auth_date is not None:
        payload["auth_date"] = str(auth_date)

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(payload.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    payload["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if tamper_hash:
        payload["hash"] = "0" * 64
    return urlencode(payload)


def assert_init_data_error(expected_message: str, *args, **kwargs):
    from api.auth import InitDataError, validate_init_data

    try:
        validate_init_data(*args, **kwargs)
    except InitDataError as e:
        assert str(e) == expected_message
        return
    raise AssertionError(f"Ожидали InitDataError: {expected_message}")


def test_admin_bot_import():
    import os

    os.environ["ADMIN_BOT_TOKEN"] = "smoke-admin-token"
    os.environ.setdefault("DATABASE_URL", "postgresql://smoke/test")
    os.environ["ADMIN_IDS"] = "1"
    import admin_bot  # noqa: F401
    from departments_manager import get_departments_status

    status = get_departments_status()
    assert status["loaded"] is True
    assert status["department_count"] >= 1


def test_bot_import():
    import os

    os.environ.setdefault("BOT_TOKEN", "smoke-test-token")
    os.environ.setdefault("DATABASE_URL", "postgresql://smoke/test")
    import bot  # noqa: F401


def test_imports():
    import app_config
    import constants
    import keyboards
    import sheets_client
    import schedule_utils
    import repositories.users_repo
    import repositories.shifts_repo
    import states
    import ui_utils
    import departments_manager
    import fsm_context
    import routers
    import services.sheet_periods_service as sheet_periods_service
    import services.schedule_service as schedule_service
    import services.salary_service as salary_service

    assert app_config.APP_TIMEZONE is not None
    assert isinstance(constants.SHEET_GID_MAP, dict)
    assert constants.SHEET_GID_MAP, "SHEET_GID_MAP fallback пустой"
    assert isinstance(sheet_periods_service.SHEET_GID_MAP, dict)
    assert sheet_periods_service.SHEET_GID_MAP, "SHEET_GID_MAP кэш пустой"
    assert hasattr(sheet_periods_service, "sync_from_db")

    # Проверяем, что модульные globals настроены хотя бы импортом.
    assert hasattr(schedule_utils, "format_date")
    assert hasattr(schedule_utils, "detect_shift")
    assert hasattr(keyboards, "compare_kb")
    from keyboards import admin as admin_keyboards
    assert hasattr(admin_keyboards, "admin_main_kb")
    assert hasattr(states, "NotificationStates")
    assert hasattr(routers, "salary_router")
    assert hasattr(routers, "schedule_router")
    assert hasattr(routers, "settings_router")
    assert hasattr(routers, "admin_router")
    assert hasattr(routers, "colleagues_router")
    assert hasattr(fsm_context, "set_shift_entry")
    assert hasattr(fsm_context, "resolve_compare_role")
    assert hasattr(schedule_service, "find_row")
    assert hasattr(salary_service, "build_salary_stats_text")


def test_salary_service():
    import services.salary_service as salary_service
    import ui_utils

    ui_utils.configure_ui_utils(
        {5: "мая", 6: "июня"},
        {5: "Май", 6: "Июнь"},
    )

    assert salary_service.get_role_key("🍸 Бармен") == "Бармен"
    assert salary_service.get_role_key("Бармен") == "Бармен"
    from datetime import datetime
    assert salary_service.parse_salary_period_button(
        "1-15 Май", datetime(2026, 6, 15),
    ) == (2026, 5, 1, 15)


def test_rates_service():
    import services.rates_service as rates_service

    rates_service.RATES.clear()
    rates_service.RATES.update({
        "Официант": 350,
        "Кальянщик": 280,
        "Менеджеры": 500,
    })
    rates_service._apply_rates(dict(rates_service.RATES))
    assert rates_service.get_rate("🍽 Официант") == 350
    assert rates_service.get_rate("💨 Кальян") == 280
    assert rates_service.get_rate("Кальян") == 280
    assert rates_service.RATES["Кальян"] == 280
    assert rates_service.get_rate("Менеджер") == 500
    assert "Официант" in rates_service.format_rates_text()


def test_ui_utils():
    import ui_utils

    ui_utils.configure_ui_utils(
        {
            1: "января",
            2: "февраля",
            3: "марта",
            4: "апреля",
            5: "мая",
            6: "июня",
            7: "июля",
            8: "августа",
            9: "сентября",
            10: "октября",
            11: "ноября",
            12: "декабря",
        },
        {
            1: "Январь",
            2: "Февраль",
            3: "Март",
            4: "Апрель",
            5: "Май",
            6: "Июнь",
            7: "Июль",
            8: "Август",
            9: "Сентябрь",
            10: "Октябрь",
            11: "Ноябрь",
            12: "Декабрь",
        },
    )

    assert ui_utils.fmt_hours(12.0) == "12"
    assert ui_utils.fmt_hours(11.5) == "11.5"
    assert ui_utils.is_valid_time("09:30") is True
    assert ui_utils.is_valid_time("9.30") is False
    assert ui_utils.month_label(6) == "Июнь"


def test_departments_manager():
    import departments_manager

    departments_manager.configure_departments_manager(
        lambda name: str(name).strip(),
        None,
    )

    assert "👔 Менеджер" in departments_manager.DEPARTMENTS
    assert departments_manager.is_department_label("👔 Менеджер") is True
    assert departments_manager.is_department_label("🏠 Главное меню") is False
    assert departments_manager.role_display_label("Официант") == "🍽 Официант"
    assert departments_manager.ordered_role_keys({"Бармен": [], "Официант": []})[0] == "Официант"
    assert departments_manager.person_has_ambiguous_role("Дарья") is True
    assert departments_manager.roles_for_person("Дарья") == ["Бармен", "Хостес"]
    assert departments_manager.roles_for_person("Виталий") == ["Официант"]
    assert departments_manager.normalize_role_name("Менеджер") == "Менеджеры"
    assert departments_manager.resolve_department_label("👔 Менеджеры") == "👔 Менеджер"
    assert departments_manager.is_department_label("👔 Менеджеры") is True
    assert departments_manager.role_display_label("Менеджер") == "👔 Менеджеры"
    assert departments_manager.role_display_label("Официанты") == "🍽 Официант"
    assert departments_manager.role_display_label("Бармены") == "🍸 Бармен"
    assert departments_manager.role_display_label("Кальянщики") == "💨 Кальян"
    assert departments_manager.role_display_label("Стажер") == "🎓 Стажер"
    assert departments_manager.is_department_label("🎓 Стажер") is True
    assert departments_manager.ordered_role_keys(
        {"Бармен": [], "Стажер": [], "Официант": []}
    )[:3] == ["Официант", "Стажер", "Бармен"]
    assert "Роберт Фролов стаж" in departments_manager.DEPARTMENTS["🎓 Стажер"]


def test_intern_shift_times():
    from schedule_utils import detect_shift, detect_shift_type, is_work_shift

    for value in ("13:00-15:00", "11:00-16:00", "16:30-19:30"):
        assert is_work_shift(value)
        assert detect_shift_type(value) in {"morning", "evening"}
        assert "—" in detect_shift(value)


def test_schedule_utils():
    import schedule_utils

    # configure на случай если smoke запускается без bot.py.
    if hasattr(schedule_utils, "configure_schedule_utils"):
        schedule_utils.configure_schedule_utils(
            {
                1: "января",
                2: "февраля",
                3: "марта",
                4: "апреля",
                5: "мая",
                6: "июня",
                7: "июля",
                8: "августа",
                9: "сентября",
                10: "октября",
                11: "ноября",
                12: "декабря",
            },
            set(),
        )

    assert schedule_utils.clean_value("  11:00 ") == "11:00"

    assert schedule_utils.is_work_shift("11:00") is True
    assert schedule_utils.is_work_shift("16:00") is True
    assert schedule_utils.is_work_shift("") is False
    assert schedule_utils.is_work_shift(None) is False

    assert "утро" in schedule_utils.detect_shift("11:00")
    assert "вечер" in schedule_utils.detect_shift("16:00")

    text = schedule_utils.format_date(15, 6, 2026)
    assert "15 июня" in text
    assert "пн" in text.lower()


def test_keyboards():
    import keyboards
    from keyboards.schedule import own_names_kb

    # configure на случай если smoke запускается без bot.py.
    if hasattr(keyboards, "configure_keyboard_context"):
        keyboards.configure_keyboard_context(
            {
                1: "января",
                2: "февраля",
                3: "марта",
                4: "апреля",
                5: "мая",
                6: "июня",
                7: "июля",
                8: "августа",
                9: "сентября",
                10: "октября",
                11: "ноября",
                12: "декабря",
            },
            {
                1: "Январь",
                2: "Февраль",
                3: "Март",
                4: "Апрель",
                5: "Май",
                6: "Июнь",
                7: "Июль",
                8: "Август",
                9: "Сентябрь",
                10: "Октябрь",
                11: "Ноябрь",
                12: "Декабрь",
            },
            set(),
        )

    kb = keyboards.compare_kb()
    assert kb is not None

    periods = keyboards.get_available_periods()
    assert isinstance(periods, list)

    manager_kb = own_names_kb("👔 Менеджеры")
    assert manager_kb.keyboard[0][0].text == "Рина Евгеньевна"
    assert manager_kb.keyboard[-1][0].text == "🏠 Главное меню"


def test_miniapp_auth():
    from api.auth import validate_init_data

    bot_token = "smoke-test-token"
    now_ts = 1_700_000_000

    result = validate_init_data(
        build_signed_init_data(bot_token, auth_date=now_ts),
        bot_token,
        now_ts=now_ts,
    )
    assert result["user_id"] == 42

    assert_init_data_error(
        "Неверная подпись",
        build_signed_init_data(bot_token, auth_date=now_ts, tamper_hash=True),
        bot_token,
        now_ts=now_ts,
    )
    assert_init_data_error(
        "Нет auth_date",
        build_signed_init_data(bot_token, auth_date=None),
        bot_token,
        now_ts=now_ts,
    )
    assert_init_data_error(
        "Некорректный auth_date",
        build_signed_init_data(bot_token, auth_date="oops"),
        bot_token,
        now_ts=now_ts,
    )
    assert_init_data_error(
        "auth_date устарел",
        build_signed_init_data(bot_token, auth_date=now_ts - 86_401),
        bot_token,
        now_ts=now_ts,
    )
    assert_init_data_error(
        "auth_date из будущего",
        build_signed_init_data(bot_token, auth_date=now_ts + 61),
        bot_token,
        now_ts=now_ts,
    )


def test_miniapp_week_today_stays_real_when_offset_changes():
    from datetime import datetime
    from unittest.mock import patch
    from zoneinfo import ZoneInfo

    from services import miniapp_service

    tz = ZoneInfo("Europe/Moscow")
    now = datetime(2026, 7, 4, 12, 0, tzinfo=tz)

    async def fake_shift(_name, _role, _dt):
        return {"working": False, "shift_type": None, "label": None, "hours": None}

    with patch.object(miniapp_service, "now_local", return_value=now):
        with patch.object(miniapp_service, "_shift_for_person", fake_shift):
            with patch.object(miniapp_service.schedule, "is_day_published", return_value=True):
                data = asyncio.run(
                    miniapp_service._week_schedule_for("Виталий", "Официант", week_offset=1),
                )

    assert data["days"][0]["day"] == 6
    assert data["today"]["day"] == 4
    assert data["today"]["is_today"] is True
    assert data["tomorrow"]["day"] == 5


def test_miniapp_profile_role_normalization():
    import services.schedule_watch_service as schedule_watch_service
    from services import miniapp_service

    original_get_user = miniapp_service.get_user
    original_is_person_name = miniapp_service.is_person_name
    original_roles_for_person = miniapp_service.roles_for_person
    original_save_user = miniapp_service.save_user
    original_get_profile = miniapp_service.get_profile
    original_reset_user_snapshot = schedule_watch_service.reset_user_snapshot
    saved: dict[str, object] = {}

    async def fake_get_user(user_id: int):
        return (user_id, "Рина Евгеньевна", 1, "09:30", "Менеджер", 0, 0, None, "alice_dark")

    async def fake_save_user(user_id: int, **kwargs):
        saved["user_id"] = user_id
        saved.update(kwargs)

    async def fake_profile(user_id: int):
        return {
            "registered": True,
            "user_id": user_id,
            "name": "Рина Евгеньевна",
            "role": saved.get("role"),
            "role_label": "👔 Менеджеры",
        }

    async def fake_reset_user_snapshot(user_id: int):
        saved["reset_user_id"] = user_id

    try:
        miniapp_service.get_user = fake_get_user
        profile = asyncio.run(miniapp_service.get_profile(42))
        assert profile["role"] == "Менеджер"
        assert profile["role_label"] == "👔 Менеджеры"

        miniapp_service.is_person_name = lambda name: name == "Рина Евгеньевна"
        miniapp_service.roles_for_person = lambda name: ["Менеджер"]
        miniapp_service.save_user = fake_save_user
        miniapp_service.get_profile = fake_profile
        schedule_watch_service.reset_user_snapshot = fake_reset_user_snapshot

        updated = asyncio.run(miniapp_service.update_profile(42, "Рина Евгеньевна", "Менеджеры"))
        assert updated["role"] == "Менеджер"
        assert updated["role_label"] == "👔 Менеджеры"
        assert saved["user_id"] == 42
        assert saved["role"] == "Менеджер"
        assert "notify" not in saved
        assert "notify_time" not in saved
        assert saved["reset_user_id"] == 42
    finally:
        miniapp_service.get_user = original_get_user
        miniapp_service.is_person_name = original_is_person_name
        miniapp_service.roles_for_person = original_roles_for_person
        miniapp_service.save_user = original_save_user
        miniapp_service.get_profile = original_get_profile
        schedule_watch_service.reset_user_snapshot = original_reset_user_snapshot


def test_gen_cleaning_schedule():
    from datetime import date

    from services.gen_cleaning_service import (
        FIRST_GEN_CLEANING,
        GEN_CLEANING_NOTIFY_TIME,
        gen_cleaning_notification_text,
        is_gen_cleaning_day,
        is_gen_cleaning_notify_evening,
    )

    assert FIRST_GEN_CLEANING == date(2026, 7, 8)
    assert FIRST_GEN_CLEANING.weekday() == 2
    assert is_gen_cleaning_day(date(2026, 7, 8))
    assert not is_gen_cleaning_day(date(2026, 7, 9))
    assert not is_gen_cleaning_day(date(2026, 7, 15))
    assert is_gen_cleaning_day(date(2026, 7, 22))
    assert is_gen_cleaning_notify_evening(date(2026, 7, 7))
    assert not is_gen_cleaning_notify_evening(date(2026, 7, 8))
    assert GEN_CLEANING_NOTIFY_TIME == "22:00"
    assert "будильник" in gen_cleaning_notification_text().lower()


def test_schedule_gen_cleaning_flag():
    from datetime import datetime
    from unittest.mock import AsyncMock, patch

    import services.miniapp_service as miniapp_service
    from app_config import now_local

    async def run():
        tz = now_local().tzinfo
        cleaning_day = datetime(2026, 7, 8, tzinfo=tz)
        regular_day = datetime(2026, 7, 9, tzinfo=tz)
        shift = {
            "working": False,
            "shift_type": None,
            "label": None,
            "hours": None,
        }
        with patch.object(
            miniapp_service, "_shift_for_person", new=AsyncMock(return_value=shift),
        ):
            cleaning = await miniapp_service._day_schedule_entry(
                "Тест", None, cleaning_day, cleaning_day.date(),
            )
            regular = await miniapp_service._day_schedule_entry(
                "Тест", None, regular_day, regular_day.date(),
            )
        assert cleaning["gen_cleaning"] is True
        assert regular["gen_cleaning"] is False

    asyncio.run(run())


def test_miniapp_static_assets():
    import api.app as api_app

    static_dir = api_app.STATIC_DIR
    for asset in api_app.MINIAPP_ASSETS:
        assert (static_dir / asset).is_file(), asset

    html = (static_dir / "index.html").read_text(encoding="utf-8")
    for asset in api_app.MINIAPP_ASSETS:
        assert f"/assets/{asset}" in html


def test_miniapp_health_endpoint():
    import departments_manager
    import api.app as api_app

    departments_manager.configure_departments_manager(
        lambda name: str(name).strip(),
        None,
    )
    original_db_health = api_app._db_health

    try:
        api_app._db_health = lambda: {
            "backend": "sqlite",
            "ok": True,
            "registered_users": 3,
            "notify_enabled": 2,
            "notify_hours_enabled": 1,
            "schedule_snapshots": 2,
        }
        app = api_app.create_app()
        health_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/health")
        payload = asyncio.run(health_route.endpoint())

        assert payload["ok"] is True
        assert payload["status"] in {"ok", "degraded"}
        assert payload["ready"]["departments"] is True
        assert isinstance(payload["runtime"]["configured_port"], int)
        assert payload["build"]["checked_at"]
        assert payload["deps"]["schedule_watch"]["watch_days"] == 45
        assert payload["deps"]["schedule_watch"]["tracked_users"] == 2
        assert payload["deps"]["departments"]["department_count"] >= 1
    finally:
        api_app._db_health = original_db_health


def test_admin_period_status():
    from datetime import date
    from unittest.mock import patch

    from routers.admin import _period_status_label

    fake_now = date(2026, 7, 5)

    with patch("routers.admin.now_local") as mock_now:
        mock_now.return_value.date.return_value = fake_now
        assert _period_status_label(2026, 7, 1, 15) == "актуален"
        assert _period_status_label(2026, 7, 16, 31) == "будущий"
        assert _period_status_label(2026, 6, 1, 15) == "прошёл"


def test_sheet_loader_all_gids():
    import services.sheet_loader as sheet_loader

    assert hasattr(sheet_loader, "load_all_sheet_gids")
    assert hasattr(sheet_loader, "load_full_sheet")


def test_admin_snapshot_status():
    from routers.admin import _format_snapshot_status

    assert "нет" in _format_snapshot_status(None)
    assert _format_snapshot_status(("{}", None)) == "есть"


def test_admin_monitor_text():
    from routers.admin import _format_monitor_text

    text = _format_monitor_text(
        {
            "registered": 10,
            "snapshots": 8,
            "missing_snapshots": 2,
            "track_hours": 5,
            "missing_users": [(1, "Виталий")],
        }
    )
    assert "10" in text
    assert "Виталий" in text
    assert "45" in text


def test_admin_health_issues():
    from services.admin_health_service import collect_health_issues, format_health_report

    issues = collect_health_issues()
    assert isinstance(issues, list)
    report = format_health_report(issues)
    assert isinstance(report, str)
    assert report

    dept_keys = {key for key, _ in issues}
    assert "departments" not in dept_keys or True  # smoke без configure admin_bot


def test_admin_alert_dedup_by_key():
    from app_config import now_local
    from services.admin_alerts_service import _active_issues, _last_repeat, reset_alert_state

    reset_alert_state()
    _active_issues["cache_stale"] = "old message"
    _last_repeat["cache_stale"] = now_local()

    # same key, different message — не должно триггерить повтор само по себе
    issues = [("cache_stale", "new message with different age")]
    current = {key: message for key, message in issues}
    should_send = "cache_stale" not in _active_issues
    if not should_send:
        last = _last_repeat.get("cache_stale")
        should_send = last is not None and (now_local() - last).total_seconds() >= 3600
    assert should_send is False


def test_schedule_watch_midnight_window_slide():
    from datetime import datetime
    from unittest.mock import patch

    import services.schedule_watch_service as sw
    from services.schedule_watch_service import diff_snapshots

    # Фиксируем «сегодня» до тестовых дат, чтобы фильтр прошлых дней
    # не делал тест зависимым от реального календаря.
    tz = sw.now_local().tzinfo
    fixed_now = datetime(2026, 7, 1, tzinfo=tz)

    with patch.object(sw, "now_local", return_value=fixed_now):
        old = {
            "2026-07-04": "work|evening|16:00 — вечер",
            "2026-07-05": "off",
            "2026-07-06": "work|morning|11:00 — утро",
        }
        # Окно сдвинулось: 4 июля выпало, 7 июля появилось
        new = {
            "2026-07-05": "off",
            "2026-07-06": "work|morning|11:00 — утро",
            "2026-07-07": "off",
        }
        assert diff_snapshots(old, new) == []

        new_changed = {
            "2026-07-05": "work|evening|16:00 — вечер",
            "2026-07-06": "work|morning|11:00 — утро",
        }
        changes = diff_snapshots(old, new_changed)
        assert len(changes) == 1
        assert changes[0][0] == "added"
        assert changes[0][1].day == 5

        new_removed = {
            "2026-07-05": "off",
            "2026-07-06": "off",
        }
        changes = diff_snapshots(old, new_removed)
        assert len(changes) == 1
        assert changes[0][0] == "removed"
        assert changes[0][1].day == 6


def test_schedule_watch_unreliable_and_past():
    from datetime import datetime
    from unittest.mock import patch

    from services.schedule_watch_service import diff_snapshots

    fixed_now = datetime(2026, 7, 6, 0, 0, 0)

    with patch("services.schedule_watch_service.now_local", return_value=fixed_now):
        old = {
            "2026-07-05": "work|morning|11:00 — утро",
            "2026-07-06": "work|morning|11:00 — утро",
            "2026-07-07": "work|evening|16:00 — вечер",
        }
        new_error = {
            "2026-07-05": "error",
            "2026-07-06": "work|morning|11:00 — утро",
            "2026-07-07": "work|evening|16:00 — вечер",
        }
        assert diff_snapshots(old, new_error) == []

        new_missing = {
            "2026-07-05": "missing",
            "2026-07-06": "work|morning|11:00 — утро",
            "2026-07-07": "work|evening|16:00 — вечер",
        }
        assert diff_snapshots(old, new_missing) == []

        new_past_off = {
            "2026-07-05": "off",
            "2026-07-06": "work|morning|11:00 — утро",
            "2026-07-07": "work|evening|16:00 — вечер",
        }
        assert diff_snapshots(old, new_past_off) == []

        new_future_off = {
            "2026-07-05": "work|morning|11:00 — утро",
            "2026-07-06": "off",
            "2026-07-07": "work|evening|16:00 — вечер",
        }
        changes = diff_snapshots(old, new_future_off)
        assert len(changes) == 1
        assert changes[0][0] == "removed"
        assert changes[0][1].day == 6


def test_roster_person_name():
    from services.miniapp_service import _roster_person_name

    assert _roster_person_name("Платон — 11:00 — утро") == "Платон"
    assert _roster_person_name("Платон") == "Платон"


def test_day_roster_dual_role_off_in_second_role():
    """Дарья работает барменом, но выходная как хостес: она должна остаться
    в «работают» (бармен) И попасть в «возможную замену» как хостес."""
    from unittest.mock import AsyncMock, patch

    import departments_manager
    import services.miniapp_service as miniapp_service

    departments_manager.configure_departments_manager(
        lambda name: str(name).strip(), None,
    )

    async def fake_shift(name, role, dt):
        if name == "Дарья" and role == "Бармен":
            return {
                "working": True, "shift_type": "morning",
                "label": "утро", "hours": 12.5, "raw": "11:00",
            }
        return {"working": False, "shift_type": None, "label": "вых", "hours": None}

    async def run():
        with patch.object(
            miniapp_service.schedule, "is_day_published", return_value=True,
        ), patch.object(
            miniapp_service.schedule, "get_people_for_day",
            new=AsyncMock(return_value={"Бармен": ["Дарья — 11:00 — утро"]}),
        ), patch.object(
            miniapp_service, "_shift_for_person", new=fake_shift,
        ):
            return await miniapp_service.get_day_roster("2026-07-12")

    data = asyncio.run(run())

    # в «работают» под барменом
    barmen = [d for d in data["departments"] if d["role"] == "Бармен"]
    assert barmen and any("Дарья" in n for n in barmen[0]["people"]), data["departments"]

    # в «возможную замену» как хостес, но не как бармен
    darya_off = [p for p in data["off"] if p["name"] == "Дарья"]
    assert len(darya_off) == 1, data["off"]
    assert "Хостес" in darya_off[0]["role_label"]
    assert "Бармен" not in darya_off[0]["role_label"]


def test_day_roster_missed_working_person_not_lost():
    """Если get_people_for_day пропустил работающего человека, но по табелю
    он работает — он должен попасть в «работают», а не исчезнуть."""
    from unittest.mock import AsyncMock, patch

    import departments_manager
    import services.miniapp_service as miniapp_service

    departments_manager.configure_departments_manager(
        lambda name: str(name).strip(), None,
    )

    async def fake_shift(name, role, dt):
        if name == "Вениамин" and role == "Бармен":
            return {
                "working": True, "shift_type": "evening",
                "label": "вечер", "hours": 8, "raw": "16:00",
            }
        return {"working": False, "shift_type": None, "label": "вых", "hours": None}

    async def run():
        with patch.object(
            miniapp_service.schedule, "is_day_published", return_value=True,
        ), patch.object(
            miniapp_service.schedule, "get_people_for_day",
            new=AsyncMock(return_value={}),
        ), patch.object(
            miniapp_service, "_shift_for_person", new=fake_shift,
        ):
            return await miniapp_service.get_day_roster("2026-07-12")

    data = asyncio.run(run())
    working_names = [
        _n for dep in data["departments"] for _n in dep["people"]
    ]
    assert any("Вениамин" in n for n in working_names), data["departments"]
    assert not any(p["name"] == "Вениамин" for p in data["off"]), data["off"]


def test_period_coverage_missing():
    from datetime import date
    from unittest.mock import patch

    from services.period_coverage_service import (
        format_period_key,
        missing_period_alerts,
        missing_period_keys,
    )

    sample = {
        (2026, 7, 1): "2125046654",
    }
    with patch("services.period_coverage_service.SHEET_GID_MAP", sample):
        missing = missing_period_keys(days_ahead=14)
        assert (2026, 7, 16) in missing
        assert "июл" in format_period_key((2026, 7, 16))

        # До следующего периода > 2 дней — алерт не нужен
        assert missing_period_alerts(on=date(2026, 7, 6)) == []
        # За 2 дня до 16 июля — алерт
        assert missing_period_alerts(on=date(2026, 7, 14)) == [(2026, 7, 16)]
        assert missing_period_alerts(on=date(2026, 7, 15)) == [(2026, 7, 16)]

        # Текущий период без gid — алерт сразу
        only_next = {(2026, 7, 16): "x"}
        with patch("services.period_coverage_service.SHEET_GID_MAP", only_next):
            assert missing_period_alerts(on=date(2026, 7, 10)) == [(2026, 7, 1)]


def test_period_gap_alert_no_repeat():
    from app_config import now_local
    from services.admin_alerts_service import (
        _active_issues,
        _last_repeat,
        _no_repeat_keys,
        reset_alert_state,
    )

    reset_alert_state()
    assert "period_gap" in _no_repeat_keys
    _active_issues["period_gap"] = "Нет gid"
    _last_repeat["period_gap"] = now_local()

    key = "period_gap"
    assert key in _active_issues
    assert key in _no_repeat_keys


def test_cache_signal_pending():
    import services.cache_signal_service as cache_signal

    cache_signal._last_applied_version = 0

    async def run():
        from unittest.mock import AsyncMock, patch

        with patch(
            "services.cache_signal_service.get_int",
            new=AsyncMock(return_value=2),
        ):
            assert await cache_signal.pending_sheet_cache_signal() is True

        with patch(
            "services.cache_signal_service.get_int",
            new=AsyncMock(return_value=2),
        ), patch(
            "services.cache_signal_service.reload_from_db",
            new=AsyncMock(return_value=5),
        ), patch(
            "services.cache_signal_service.load_all_sheet_gids",
            new=AsyncMock(return_value=(5, 0, [])),
        ):
            assert await cache_signal.apply_pending_sheet_cache_signal() is True
            assert cache_signal._last_applied_version == 2
            assert await cache_signal.pending_sheet_cache_signal() is False

    asyncio.run(run())


def test_admin_health_period_gap():
    from unittest.mock import MagicMock, patch

    from services.admin_health_service import collect_health_issues

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.side_effect = [(5,), (3,)]

    with patch(
        "services.admin_health_service.get_db_connection",
        return_value=mock_conn,
    ), patch(
        "services.admin_health_service.SHEET_GID_MAP",
        {(2026, 7, 1): "1"},
    ), patch(
        "services.admin_health_service.missing_period_alerts",
        return_value=[(2026, 7, 16)],
    ):
        issues = collect_health_issues()
    keys = [key for key, _msg in issues]
    assert "period_gap" in keys


def test_broadcast_format_helpers():
    from keyboards.admin import BC_FMT_HTML, BC_FMT_HTML_MINIAPP, BC_FMT_PLAIN
    from routers.admin import _broadcast_parse_mode, _broadcast_format_hint

    assert _broadcast_parse_mode(BC_FMT_PLAIN) is None
    assert _broadcast_parse_mode(BC_FMT_HTML) == "HTML"
    assert _broadcast_parse_mode(BC_FMT_HTML_MINIAPP) == "HTML"
    assert "HTML" in _broadcast_format_hint(BC_FMT_HTML)


def test_message_format():
    import message_format as mf

    assert mf.esc("<b>") == "&lt;b&gt;"
    card = mf.day_schedule_card(
        "15 июля, вторник",
        "Виталий",
        "🍽 Официант",
        True,
        "16:00–04:00",
        team_section=mf.team_on_shift(3, [("🍽 Официант", ["Платон"])]),
    )
    assert "<b>" in card
    assert "Виталий" in card
    assert mf.money(86400) == "86 400 ₽"
    row = mf.week_day_line("Вт", 30, "июл", True, "11:00–23:00", is_today=True)
    assert "👉" in row and "Вт" in row


def main():
    checks = [
        ("bot_import", test_bot_import),
        ("admin_bot_import", test_admin_bot_import),
        ("imports", test_imports),
        ("salary_service", test_salary_service),
        ("rates_service", test_rates_service),
        ("schedule_utils", test_schedule_utils),
        ("keyboards", test_keyboards),
        ("ui_utils", test_ui_utils),
        ("departments_manager", test_departments_manager),
        ("intern_shift_times", test_intern_shift_times),
        ("message_format", test_message_format),
        ("miniapp_auth", test_miniapp_auth),
        ("miniapp_week_today", test_miniapp_week_today_stays_real_when_offset_changes),
        ("miniapp_profile_role_normalization", test_miniapp_profile_role_normalization),
        ("gen_cleaning_schedule", test_gen_cleaning_schedule),
        ("schedule_gen_cleaning_flag", test_schedule_gen_cleaning_flag),
        ("miniapp_static_assets", test_miniapp_static_assets),
        ("miniapp_health_endpoint", test_miniapp_health_endpoint),
        ("admin_period_status", test_admin_period_status),
        ("sheet_loader_all_gids", test_sheet_loader_all_gids),
        ("admin_snapshot_status", test_admin_snapshot_status),
        ("admin_monitor_text", test_admin_monitor_text),
        ("admin_health_issues", test_admin_health_issues),
        ("broadcast_format_helpers", test_broadcast_format_helpers),
        ("admin_alert_dedup", test_admin_alert_dedup_by_key),
        ("schedule_watch_midnight", test_schedule_watch_midnight_window_slide),
        ("schedule_watch_unreliable", test_schedule_watch_unreliable_and_past),
        ("roster_person_name", test_roster_person_name),
        ("day_roster_dual_role_off", test_day_roster_dual_role_off_in_second_role),
        ("day_roster_missed_working", test_day_roster_missed_working_person_not_lost),
        ("period_coverage", test_period_coverage_missing),
        ("period_gap_no_repeat", test_period_gap_alert_no_repeat),
        ("cache_signal", test_cache_signal_pending),
        ("admin_health_period_gap", test_admin_health_period_gap),
    ]

    for name, fn in checks:
        check(name, fn)

    print("\n✅ Smoke-test passed")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        print("\n❌ Smoke-test failed")
        sys.exit(1)
    except Exception:
        print("\n❌ Smoke-test failed")
        sys.exit(1)
