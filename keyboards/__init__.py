from keyboards.context import configure_keyboard_context
from keyboards.compare import compare_kb, compare_period_kb, get_available_periods, week_kb
from keyboards.main_menu import main_kb, main_kb_async
from keyboards.notifications import notifications_kb
from keyboards.salary import (
    get_shift_history_months,
    salary_kb,
    salary_period_kb,
    salary_settings_delete_kb,
    salary_settings_kb,
    shift_date_kb,
    shift_history_actions_kb,
    shift_history_delete_kb,
    shift_history_month_kb,
    shift_history_period_kb,
    shift_hours_kb,
)
from keyboards.schedule import (
    colleague_kb,
    colleague_names_kb,
    compare_names_kb,
    dep_kb,
    months_kb,
    my_schedule_kb,
    own_names_kb,
    today_tomorrow_kb,
)

__all__ = [
    "configure_keyboard_context",
    "get_available_periods",
    "compare_period_kb",
    "compare_kb",
    "week_kb",
    "main_kb",
    "main_kb_async",
    "salary_kb",
    "salary_period_kb",
    "salary_settings_kb",
    "salary_settings_delete_kb",
    "shift_date_kb",
    "shift_hours_kb",
    "get_shift_history_months",
    "shift_history_month_kb",
    "shift_history_period_kb",
    "shift_history_actions_kb",
    "shift_history_delete_kb",
    "my_schedule_kb",
    "months_kb",
    "today_tomorrow_kb",
    "colleague_kb",
    "dep_kb",
    "own_names_kb",
    "colleague_names_kb",
    "compare_names_kb",
    "notifications_kb",
]
