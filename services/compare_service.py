"""Сравнение графиков с коллегами."""

import logging
from typing import Awaitable, Callable

from aiogram.fsm.context import FSMContext

from app_config import now_local
from departments_manager import person_has_ambiguous_role, role_display_label
from fsm_context import (
    get_compare_period,
    get_compare_selected,
    resolve_compare_role,
)
from repositories.users_repo import get_user
from schedule_utils import current_period, detect_shift, format_date, is_work_shift
from ui_utils import month_label
import message_format as mf

_find_row: Callable[..., Awaitable] | None = None
_get_day_value: Callable[..., Awaitable] | None = None


def configure_compare_service(find_row, get_day_value):
    global _find_row, _get_day_value
    _find_row = find_row
    _get_day_value = get_day_value


async def compare_multiple(user_id: int, state: FSMContext) -> str:
    if _find_row is None or _get_day_value is None:
        raise RuntimeError("compare_service не настроен: вызови configure_compare_service()")

    user = await get_user(user_id)
    if not user or not user[1]:
        return "Сначала выбери своё имя."

    my_name = user[1]
    selected = sorted(await get_compare_selected(state))
    if not selected:
        return "Добавь хотя бы одного сотрудника для сравнения."

    all_people = [my_name] + selected

    period = await get_compare_period(state)
    if period:
        year, month, period_start, period_end = period
    else:
        period_start, period_end = current_period()
        now = now_local()
        month, year = now.month, now.year

    common_work = []
    common_off = []

    for day in range(period_start, period_end + 1):
        values = {}

        for name in all_people:
            target_role = await resolve_compare_role(name, state, user)
            ambiguous = person_has_ambiguous_role(name)

            row = None
            try:
                row, _ = await _find_row(name, day, month, year, target_role=target_role)
            except (ValueError, ConnectionError) as e:
                logging.warning(
                    "compare_multiple: поиск с ролью не дал данных name=%s day=%s month=%s year=%s role=%s: %s",
                    name, day, month, year, target_role, e,
                )
            except Exception as e:
                logging.exception(
                    "compare_multiple: ошибка поиска с ролью name=%s day=%s month=%s year=%s role=%s: %s",
                    name, day, month, year, target_role, e,
                )

            if not row and target_role and not ambiguous:
                try:
                    row, _ = await _find_row(name, day, month, year, target_role=None)
                    if row:
                        logging.info(
                            "compare_multiple: fallback без роли сработал name=%s day=%s month=%s year=%s old_role=%s",
                            name, day, month, year, target_role,
                        )
                except (ValueError, ConnectionError) as e:
                    logging.warning(
                        "compare_multiple: fallback без роли не дал данных name=%s day=%s month=%s year=%s: %s",
                        name, day, month, year, e,
                    )
                except Exception as e:
                    logging.exception(
                        "compare_multiple: ошибка fallback без роли name=%s day=%s month=%s year=%s: %s",
                        name, day, month, year, e,
                    )

            if not row:
                logging.warning(
                    "compare_multiple: сотрудник не найден name=%s day=%s month=%s year=%s role=%s",
                    name, day, month, year, target_role,
                )
                continue

            values[name] = await _get_day_value(row, day, month, year)

        if len(values) < len(all_people):
            continue

        if all(is_work_shift(v) for v in values.values()):
            shifts_text = " / ".join(
                f"{name}: {detect_shift(values[name])}" for name in all_people
            )
            common_work.append(f"{format_date(day, month, year)} — {shifts_text}")
        elif all(not is_work_shift(v) for v in values.values()):
            common_off.append(format_date(day, month, year))

    month_name = month_label(month)
    period_label = f"{period_start}–{period_end} {month_name} {year}"

    participants = []
    for person in all_people:
        person_role = await resolve_compare_role(person, state, user)
        role_label = role_display_label(person_role) if person_role else None
        participants.append((person, role_label))

    work_lines = []
    for item in common_work:
        work_lines.append(item)

    return mf.compare_result(participants, period_label, work_lines, common_off)
