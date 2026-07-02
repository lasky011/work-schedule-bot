from aiogram.fsm.state import State, StatesGroup


SHIFT_ENTRY = "shift_entry"
VIEWING_COLLEAGUE = "viewing_colleague"
VIEWING_COLLEAGUE_ROLE = "viewing_colleague_role"
LAST_SELECTED_DEPT = "last_selected_dept"
COMPARE_SELECTED = "compare_selected"
COMPARE_SELECTED_ROLES = "compare_selected_roles"
COMPARE_PERIOD = "compare_period"
USER_WEEK = "user_week"
SHIFT_HISTORY_MONTH = "shift_history_month"
SHIFT_HISTORY_PERIOD = "shift_history_period"


class NotificationStates(StatesGroup):
    waiting_for_time = State()


class ShiftEntryStates(StatesGroup):
    choosing_hours = State()
    waiting_custom_hours = State()


class NameFlowStates(StatesGroup):
    choosing_own_department = State()
    choosing_colleague_department = State()
    choosing_compare_department = State()
    choosing_own_name = State()


class CompareStates(StatesGroup):
    selecting_people = State()
    selecting_period = State()


class ShiftHistoryStates(StatesGroup):
    selecting_month = State()
    selecting_period = State()
    viewing_period = State()


class AdminAddPeriodStates(StatesGroup):
    choosing_month = State()
    choosing_half = State()
    waiting_gid = State()


class AdminEditPeriodStates(StatesGroup):
    waiting_gid = State()


class AdminBroadcastStates(StatesGroup):
    choosing_audience = State()
    waiting_text = State()


class AdminStatsStates(StatesGroup):
    choosing_month = State()
