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


def test_imports():
    import app_config
    import constants
    import keyboards
    import sheets_client
    import schedule_utils
    import repositories.users_repo
    import repositories.shifts_repo

    assert app_config.APP_TIMEZONE is not None
    assert isinstance(constants.SHEET_GID_MAP, dict)
    assert constants.SHEET_GID_MAP, "SHEET_GID_MAP пустой"

    # Проверяем, что модульные globals настроены хотя бы импортом.
    assert hasattr(schedule_utils, "format_date")
    assert hasattr(schedule_utils, "detect_shift")
    assert hasattr(keyboards, "compare_kb")


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
        ("imports", test_imports),
        ("schedule_utils", test_schedule_utils),
        ("keyboards", test_keyboards),
    ]

    for name, fn in checks:
        check(name, fn)

    print("\n✅ Smoke-test passed")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("\n❌ Smoke-test failed")
        sys.exit(1)
