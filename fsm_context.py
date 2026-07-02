"""FSM-хелперы: смены, коллеги, сравнение графиков."""

from datetime import datetime

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app_config import APP_TIMEZONE
from departments_manager import (
    normalize_role_name,
    person_has_ambiguous_role,
    role_display_label,
    roles_for_person,
)
from keyboards import dep_kb
from message_format import context_banner, onboarding_step, prepend_context
from repositories.users_repo import get_user, get_user_name
from states import (
    COMPARE_PERIOD,
    COMPARE_SELECTED,
    COMPARE_SELECTED_ROLES,
    LAST_SELECTED_DEPT,
    SHIFT_ENTRY,
    SHIFT_HISTORY_MONTH,
    SHIFT_HISTORY_PERIOD,
    USER_WEEK,
    CompareStates,
    NameFlowStates,
    NotificationStates,
    ShiftEntryStates,
    ShiftHistoryStates,
    VIEWING_COLLEAGUE,
    VIEWING_COLLEAGUE_ROLE,
)


async def reset_modes(user_id: int, state: FSMContext) -> None:
    await state.clear()


async def set_user_week(state: FSMContext, week_days: list) -> None:
    await state.update_data(**{
        USER_WEEK: [dt.strftime("%Y-%m-%d") for dt in week_days],
    })


async def get_user_week(state: FSMContext) -> list | None:
    raw = (await state.get_data()).get(USER_WEEK)
    if not raw:
        return None
    result = []
    for date_str in raw:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        result.append(dt.replace(tzinfo=APP_TIMEZONE))
    return result


async def get_viewing_colleague(state: FSMContext) -> str | None:
    return (await state.get_data()).get(VIEWING_COLLEAGUE)


async def get_viewing_colleague_role(state: FSMContext) -> str | None:
    return (await state.get_data()).get(VIEWING_COLLEAGUE_ROLE)


async def set_colleague_view(state: FSMContext, name: str, role: str | None) -> None:
    await state.update_data(**{VIEWING_COLLEAGUE: name, VIEWING_COLLEAGUE_ROLE: role})


async def clear_colleague_view(state: FSMContext) -> None:
    await state.update_data(**{VIEWING_COLLEAGUE: None, VIEWING_COLLEAGUE_ROLE: None})


async def set_last_selected_dept(state: FSMContext, dept: str) -> None:
    await state.update_data(**{LAST_SELECTED_DEPT: dept})


async def pop_last_selected_dept(state: FSMContext) -> str | None:
    data = await state.get_data()
    dept = data.get(LAST_SELECTED_DEPT)
    if LAST_SELECTED_DEPT in data:
        data = dict(data)
        data.pop(LAST_SELECTED_DEPT, None)
        await state.set_data(data)
    return dept


async def get_compare_selected(state: FSMContext) -> set[str]:
    raw = (await state.get_data()).get(COMPARE_SELECTED) or []
    return set(raw)


async def get_compare_selected_roles(state: FSMContext) -> dict[str, str]:
    raw = (await state.get_data()).get(COMPARE_SELECTED_ROLES) or {}
    return dict(raw)


async def set_compare_selected(state: FSMContext, names: set[str] | list[str]) -> None:
    await state.update_data(**{COMPARE_SELECTED: sorted(set(names))})


async def set_compare_selected_roles(state: FSMContext, roles: dict[str, str]) -> None:
    await state.update_data(**{COMPARE_SELECTED_ROLES: dict(roles)})


async def set_compare_person_role(state: FSMContext, name: str, role: str | None) -> None:
    roles = await get_compare_selected_roles(state)
    if role:
        roles[name] = role
    else:
        roles.pop(name, None)
    await set_compare_selected_roles(state, roles)


async def add_compare_selected_name(
    state: FSMContext, name: str, role: str | None = None,
) -> None:
    selected = await get_compare_selected(state)
    selected.add(name)
    await set_compare_selected(state, selected)
    if role:
        await set_compare_person_role(state, name, role)


async def resolve_compare_role(
    name: str, state: FSMContext, user: tuple | None,
) -> str | None:
    my_name = user[1] if user else None
    my_role = user[4] if user else None
    if name == my_name and my_role:
        return normalize_role_name(my_role)

    colleague = await get_viewing_colleague(state)
    if name == colleague:
        colleague_role = await get_viewing_colleague_role(state)
        if colleague_role:
            return normalize_role_name(colleague_role)

    stored = await get_compare_selected_roles(state)
    if name in stored and stored[name]:
        return normalize_role_name(stored[name])

    matches = roles_for_person(name)
    if len(matches) == 1:
        return normalize_role_name(matches[0])

    return None


async def get_compare_period(state: FSMContext) -> tuple | None:
    raw = (await state.get_data()).get(COMPARE_PERIOD)
    return tuple(raw) if raw else None


async def set_compare_period(state: FSMContext, period: tuple) -> None:
    await state.update_data(**{COMPARE_PERIOD: list(period)})


async def is_comparing(state: FSMContext) -> bool:
    current = await state.get_state()
    return current in {
        CompareStates.selecting_people.state,
        CompareStates.selecting_period.state,
        NameFlowStates.choosing_compare_department.state,
    }


async def reset_compare_mode(state: FSMContext) -> None:
    await state.update_data(**{
        COMPARE_SELECTED: [],
        COMPARE_SELECTED_ROLES: {},
        COMPARE_PERIOD: None,
    })
    current = await state.get_state()
    if current in {
        CompareStates.selecting_people.state,
        CompareStates.selecting_period.state,
        NameFlowStates.choosing_compare_department.state,
    }:
        await state.set_state(None)


async def selected_compare_text(state: FSMContext) -> str:
    selected = sorted(await get_compare_selected(state))

    if not selected:
        return "<b>Выбранные сотрудники:</b>\nпока никого."

    roles = await get_compare_selected_roles(state)
    lines = ["<b>Выбранные сотрудники:</b>"]
    for name in selected:
        role = roles.get(name)
        if not role and person_has_ambiguous_role(name):
            role = await resolve_compare_role(name, state, None)
        if role:
            lines.append(f"  • {name} ({role_display_label(role)})")
        else:
            lines.append(f"  • {name}")
    return "\n".join(lines)


async def viewing_context_line(state: FSMContext) -> str | None:
    colleague = await get_viewing_colleague(state)
    if not colleague:
        return None
    role = await get_viewing_colleague_role(state)
    role_label = role_display_label(role) if role else None
    return context_banner(colleague, role_label)


async def with_viewing_context(state: FSMContext, body: str) -> str:
    return prepend_context(await viewing_context_line(state), body)


async def prompt_choose_own_name(message: Message, state: FSMContext):
    await state.set_state(NameFlowStates.choosing_own_department)
    from ui_utils import answer_html

    text = onboarding_step(1, 3, "Выбери <b>подразделение</b>")
    return await answer_html(message, text, reply_markup=dep_kb())


async def active_name(user_id: int, state: FSMContext):
    colleague = await get_viewing_colleague(state)
    if colleague:
        return colleague
    return await get_user_name(user_id)


async def active_role(user_id: int, state: FSMContext):
    if await get_viewing_colleague(state):
        return await get_viewing_colleague_role(state)
    user = await get_user(user_id)
    return user[4] if user else None


async def clear_notification_state(state: FSMContext) -> None:
    if await state.get_state() == NotificationStates.waiting_for_time.state:
        await state.set_state(None)


# ── учёт смен (salary-роутер) ──────────────────────────────────────────────


async def set_shift_history_month(state: FSMContext, year: int, month: int) -> None:
    await state.update_data(**{SHIFT_HISTORY_MONTH: [year, month]})
    await state.set_state(ShiftHistoryStates.selecting_period)


async def get_shift_history_month(state: FSMContext) -> tuple | None:
    raw = (await state.get_data()).get(SHIFT_HISTORY_MONTH)
    return tuple(raw) if raw else None


async def set_shift_history_period(
    state: FSMContext, year: int, month: int, start_day: int, end_day: int,
) -> None:
    await state.update_data(**{
        SHIFT_HISTORY_MONTH: [year, month],
        SHIFT_HISTORY_PERIOD: [year, month, start_day, end_day],
    })
    await state.set_state(ShiftHistoryStates.viewing_period)


async def get_shift_history_period(state: FSMContext) -> tuple | None:
    raw = (await state.get_data()).get(SHIFT_HISTORY_PERIOD)
    return tuple(raw) if raw else None


async def get_shift_entry(state: FSMContext) -> dict | None:
    return (await state.get_data()).get(SHIFT_ENTRY)


async def set_shift_entry(state: FSMContext, entry: dict) -> None:
    await state.update_data(**{SHIFT_ENTRY: entry})
    await state.set_state(ShiftEntryStates.choosing_hours)


async def clear_shift_entry_state(state: FSMContext) -> None:
    current = await state.get_state()
    if current in {
        ShiftEntryStates.choosing_hours.state,
        ShiftEntryStates.waiting_custom_hours.state,
    }:
        await state.update_data(**{SHIFT_ENTRY: None})
        await state.set_state(None)


async def finish_shift_entry(state: FSMContext) -> None:
    await state.update_data(**{SHIFT_ENTRY: None})
    await state.set_state(None)
