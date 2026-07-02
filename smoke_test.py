"""
Лёгкий smoke-test проекта.

Запуск:
    python3 smoke_test.py

Цель:
- проверить импорты модулей;
- поймать NameError/ImportError после рефакторинга;
- проверить базовые чистые функции без Telegram API, PostgreSQL и Google Sheets.
"""

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


def test_admin_bot_import():
    import os

    os.environ["ADMIN_BOT_TOKEN"] = "smoke-admin-token"
    os.environ.setdefault("DATABASE_URL", "postgresql://smoke/test")
    os.environ["ADMIN_IDS"] = "1"
    import admin_bot  # noqa: F401


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


def main():
    checks = [
        ("bot_import", test_bot_import),
        ("admin_bot_import", test_admin_bot_import),
        ("imports", test_imports),
        ("salary_service", test_salary_service),
        ("schedule_utils", test_schedule_utils),
        ("keyboards", test_keyboards),
        ("ui_utils", test_ui_utils),
        ("departments_manager", test_departments_manager),
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
