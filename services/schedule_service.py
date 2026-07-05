"""Google Sheets: поиск смен, форматирование графика."""

import calendar
import logging
import re
from datetime import date, datetime, timedelta

from app_config import now_local
from services.sheet_periods_service import SHEET_GID_MAP
from departments_manager import (
    SHEET_ROLES,
    normalize_role_name,
    ordered_role_keys,
    role_display_label,
)
from schedule_utils import clean_value, detect_shift, format_date, is_work_shift
from repositories.users_repo import get_user
import message_format as mf

SCHEDULE_MAX_DAY_COL = 16
ROLES = SHEET_ROLES

MONTHS = None
RU_HOLIDAYS = None
_load_sheet = None


def configure_schedule_service(load_sheet, months, ru_holidays):
    global _load_sheet, MONTHS, RU_HOLIDAYS
    _load_sheet = load_sheet
    MONTHS = months
    RU_HOLIDAYS = ru_holidays


def _clean_person_name_value(name) -> str:
    """
    Низкоуровневая очистка имени из Google Sheets.

    Пример:
    "Егор Капустин C 16:00" -> "Егор Капустин"
    """
    if name is None:
        return ""

    text = str(name).replace("\xa0", " ").strip()
    text = re.sub(r"\s+", " ", text)

    # Убираем хвосты вида "с 16:00", "С 16:00", "C 16:00".
    # Латинская C тоже учитывается.
    text = re.sub(r"\s+[сcСC]\s*\d{1,2}[:.]\d{2}\s*$", "", text).strip()

    return text


def clean_person_name(name: str) -> str:
    """
    Чистит имя сотрудника от служебных пометок в таблице.
    """
    return _clean_person_name_value(name)
def get_gid_for_day(day):
    now = now_local()
    return get_gid_for_day_month(day, now.month, now.year)

def get_gid_for_day_month(day, month, year):
    period_start = 1 if day <= 15 else 16
    return SHEET_GID_MAP.get((year, month, period_start))
def is_day_published(day, month=None, year=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year
    has_gid = get_gid_for_day_month(day, month, year) is not None
    return has_gid
def unique_keep_order(items):
    """Убирает точные дубли, сохраняя порядок."""
    seen = set()
    result = []
    for item in items:
        key = str(item).strip()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
def get_day_column(df, day):
    for i in range(len(df)):
        first = str(df.iloc[i, 0]).strip()

        if first in ROLES:
            row = df.iloc[i].fillna("").astype(str).tolist()

            for col_index, value in enumerate(row[:SCHEDULE_MAX_DAY_COL + 1]):
                if str(value).strip() == str(day):
                    return col_index

    return None
def normalize_person_lookup_name(name: str | None) -> str:
    """Нормализация имени для поиска сотрудника в Google Sheets."""
    if name is None:
        return ""

    text = _clean_person_name_value(name)
    text = text.replace("ё", "е").replace("Ё", "Е")
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


async def find_row(name, day, month=None, year=None, target_role=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year
    df = await _load_sheet(day, month, year)
    role = None
    target_role_norm = normalize_role_name(target_role)
    needle = str(name).strip().lower()
    needle_norm = normalize_person_lookup_name(name)

    for i in range(len(df)):
        first = str(df.iloc[i, 0]).strip()
        if first in ROLES:
            role = normalize_role_name(first)
            continue
        row = df.iloc[i].fillna("").astype(str).tolist()
        if needle and needle in " ".join(row).lower():
            if target_role_norm is None or role == target_role_norm:
                return row, role

    # Fallback: точный поиск по первой колонке с нормализацией имени.
    # Нужен для листов 16-30, где роль/строка может отличаться от выбранной кнопки.
    role = None
    for i in range(len(df)):
        first = str(df.iloc[i, 0]).replace("\xa0", " ").strip()
        first_clean = _clean_person_name_value(first)

        if first in ROLES:
            role = normalize_role_name(first)
            continue

        if not first_clean:
            continue

        first_norm = normalize_person_lookup_name(first_clean)
        if first_norm == needle_norm:
            if target_role_norm is None or role == target_role_norm:
                row = df.iloc[i].fillna("").astype(str).tolist()
                logging.info(
                    "find_row fallback matched name=%s day=%s month=%s year=%s role=%s target_role=%s",
                    name, day, month, year, role, target_role_norm,
                )
                return row, role

    return None, None
async def get_day_value(row, day, month=None, year=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year
    df = await _load_sheet(day, month, year)
    col = get_day_column(df, day)

    if col is None or col >= len(row):
        return ""

    return row[col]


async def get_people_for_day(day, month=None, year=None):
    """
    Возвращает всех работающих за день по всем подразделениям Google Sheets.

    Поддерживает листы, где внутри одного листа есть несколько блоков с повторными строками дат.
    Например: Менеджеры/Официанты/Бармены, потом ниже Кальян со своим заголовком дат.
    """
    now = now_local()
    month = month or now.month
    year = year or now.year

    try:
        df = await _load_sheet(day, month, year)
    except Exception as e:
        logging.exception("get_people_for_day: ошибка load_sheet day=%s month=%s year=%s: %s", day, month, year, e)
        return {}

    role_aliases = {
        "менеджеры": "Менеджеры",
        "менеджер": "Менеджеры",
        "официант": "Официант",
        "официанты": "Официант",
        "бармен": "Бармен",
        "бармены": "Бармен",
        "кальян": "Кальян",
        "кальянщик": "Кальян",
        "кальянщики": "Кальян",
        "хостес": "Хостес",
    }

    weekdays = {"вт", "ср", "чт", "пт", "сб", "вс", "пн"}

    def detect_role_from_cell(value):
        text = str(value or "").replace("\xa0", " ").strip()
        text_norm = re.sub(r"\s+", " ", text).lower()
        return role_aliases.get(text_norm)

    def find_day_col_in_row(row_idx: int):
        """Если строка содержит номер нужного дня, возвращает колонку."""
        try:
            for col in range(1, min(len(df.columns), SCHEDULE_MAX_DAY_COL + 1)):
                cell = df.iat[row_idx, col]
                cell_text = clean_value(cell)
                if cell_text == str(day):
                    return col
        except Exception:
            return None
        return None

    result = {}
    current_role = None
    current_day_col = None

    # Начальный fallback: старый способ, если строка дат ещё не встретилась.
    try:
        current_day_col = get_day_column(df, day)
    except Exception:
        current_day_col = None

    for i in range(len(df)):
        raw_first = df.iat[i, 0] if len(df.columns) > 0 else ""
        first_text = str(raw_first or "").replace("\xa0", " ").strip()

        # 1. Колонку дня берём один раз через get_day_column(df, day).
        # Не обновляем её по строкам ниже: в правом блоке статистики есть числа,
        # которые можно ошибочно принять за дни графика.
        # row_day_col = find_day_col_in_row(i)

        if not first_text or first_text.lower() == "nan":
            continue

        # 2. Если это заголовок подразделения, меняем текущую роль.
        detected_role = detect_role_from_cell(first_text)
        if detected_role:
            current_role = detected_role
            result.setdefault(current_role, [])

            # Часто сразу следующая строка после роли содержит даты.
            # Но если дата уже есть в этой строке, current_day_col уже обновился выше.
            continue

        if not current_role or current_day_col is None:
            continue

        name = _clean_person_name_value(first_text)
        if not name:
            continue

        lower_name = name.lower().strip()

        # 3. Пропускаем служебные строки.
        if lower_name in weekdays:
            continue
        if lower_name.isdigit():
            continue
        if "кол-во" in lower_name or "смен" in lower_name:
            continue
        if lower_name in role_aliases:
            continue

        try:
            value = df.iat[i, current_day_col]
        except Exception:
            continue

        if not is_work_shift(value):
            continue

        result.setdefault(current_role, [])
        result[current_role].append(f"{name} — {detect_shift(value)}")

    cleaned = {}
    for role, people in result.items():
        people = unique_keep_order(people) if "unique_keep_order" in globals() else list(dict.fromkeys(people))
        if people:
            cleaned[role] = people

    logging.info(
        "get_people_for_day: day=%s month=%s year=%s roles=%s total=%s",
        day, month, year, {k: len(v) for k, v in cleaned.items()}, sum(len(v) for v in cleaned.values())
    )

    return cleaned



async def get_common_day_off_people(name, day, month=None, year=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year
    df = await _load_sheet(day, month, year)
    col = get_day_column(df, day)

    if col is None:
        return []

    result = []
    for i in range(len(df)):
        first = str(df.iloc[i, 0]).strip()
        if first in ROLES:
            continue
        row = df.iloc[i].fillna("").astype(str).tolist()
        if len(row) <= col:
            continue
        person_name = clean_value(row[0])
        value = row[col]
        if person_name and person_name != name and not is_work_shift(value):
            result.append(clean_person_name(person_name))

    return result

async def get_my_status_for_day(user_id, day, month=None, year=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year
    _user = await get_user(user_id)
    my_name = _user[1] if _user else None
    my_role = _user[4] if _user else None

    if not my_name:
        return "👤 Твоё имя не выбрано."

    if not is_day_published(day, month, year):
        return "👤 Твой график: график пока не составлен."

    row, _ = await find_row(my_name, day, month, year, target_role=my_role)
    if not row:
        return f"👤 Твой график: не нашёл имя {my_name}."

    value = await get_day_value(row, day, month, year)
    if is_work_shift(value):
        return f"✅ Ты работаешь: <code>{mf.esc(detect_shift(value))}</code>"

    return "🏖 Ты отдыхаешь."

async def get_day_schedule(name, day, month=None, year=None, target_role=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year

    max_day = calendar.monthrange(year, month)[1]

    if day > max_day:
        return "Такой даты в этом месяце нет."

    if not is_day_published(day, month, year):
        return mf.empty_state(
            "📭",
            f"{format_date(day, month, year)}",
            "График пока не составлен",
        )

    row, role = await find_row(name, day, month, year, target_role=target_role)

    if not row:
        return mf.empty_state("📋", f"Не нашёл график для {name}")

    role_label = role_display_label(role) if role else None
    value = await get_day_value(row, day, month, year)
    working = is_work_shift(value)
    shift_line = detect_shift(value) if working else None

    people_by_role = await get_people_for_day(day, month, year)
    role_blocks = [
        (role_display_label(role_key), people)
        for role_key in ordered_role_keys(people_by_role)
        for people in [people_by_role.get(role_key, [])]
        if people
    ]
    total_on_shift = sum(len(v) for v in people_by_role.values())
    team_section = mf.team_on_shift(total_on_shift, role_blocks) if role_blocks else None

    off_section = None
    if not working:
        common_off = await get_common_day_off_people(name, day, month, year)
        if common_off:
            off_section = mf.day_off_together(unique_keep_order(common_off))

    return mf.day_schedule_card(
        format_date(day, month, year),
        name,
        role_label,
        working,
        shift_line,
        team_section,
        off_section,
    )


async def get_range_schedule(name, start_day, end_day, month=None, year=None, target_role=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year

    max_day = calendar.monthrange(year, month)[1]
    end_day = min(end_day, max_day)

    saved_role = None
    found_any = False
    role_line_index = None
    unpublished_start = None
    day_lines: list[str] = []

    for day in range(start_day, end_day + 1):
        if not is_day_published(day, month, year):
            if unpublished_start is None:
                unpublished_start = day
            continue

        if unpublished_start is not None:
            if unpublished_start == day - 1:
                day_lines.append(
                    f"{unpublished_start} {MONTHS[month]} — график пока не составлен"
                )
            else:
                day_lines.append(
                    f"{unpublished_start}–{day - 1} {MONTHS[month]} — график пока не составлен"
                )
            unpublished_start = None

        row, role = await find_row(name, day, month, year, target_role=target_role)

        if row:
            found_any = True
            if role:
                saved_role = role
            value = await get_day_value(row, day, month, year)
        else:
            value = ""

        if role_line_index is None and role:
            saved_role = role
            role_line_index = 1

        day_lines.append(mf.range_schedule_day(format_date(day, month, year), detect_shift(value)))

    if unpublished_start is not None:
        if unpublished_start == end_day:
            day_lines.append(f"{unpublished_start} {MONTHS[month]} — график пока не составлен")
        else:
            day_lines.append(
                f"{unpublished_start}–{end_day} {MONTHS[month]} — график пока не составлен"
            )

    if not found_any:
        return mf.empty_state("📭", f"Не нашёл график для {name}")

    if saved_role:
        header = mf.range_schedule_header(name, role_display_label(saved_role))
    else:
        header = mf.range_schedule_header(name, None)

    return header + "\n".join(day_lines)


async def build_today_summary(name, role, user_id, track_hours: bool = False) -> str:
    """Карточка «Сегодня» — смена, завтра, подсказка по часам."""
    now = now_local()
    today = now.day
    month = now.month
    year = now.year

    role_label = role_display_label(role) if role else None

    if not is_day_published(today, month, year):
        today_line = "📭 График на сегодня ещё не составлен"
        tomorrow_hint = None
    else:
        row, _ = await find_row(name, today, month, year, target_role=role)
        if not row:
            today_line = "📋 Тебя нет в графике на сегодня"
        else:
            value = await get_day_value(row, today, month, year)
            if is_work_shift(value):
                today_line = f"✅ Работаешь — <code>{mf.esc(detect_shift(value))}</code>"
            else:
                today_line = "🏖 Выходной"

        tomorrow_dt = now + timedelta(days=1)
        tomorrow_hint = None
        if is_day_published(tomorrow_dt.day, tomorrow_dt.month, tomorrow_dt.year):
            try:
                t_row, _ = await find_row(
                    name, tomorrow_dt.day, tomorrow_dt.month, tomorrow_dt.year, target_role=role,
                )
                if t_row:
                    t_val = await get_day_value(t_row, tomorrow_dt.day, tomorrow_dt.month, tomorrow_dt.year)
                    if is_work_shift(t_val):
                        tomorrow_hint = f"✅ {detect_shift(t_val)}"
                    else:
                        tomorrow_hint = "🏖 выходной"
            except Exception:
                pass

    hours_hint = "⏱ Не забудь внести часы после смены" if track_hours else None

    return mf.today_summary_card(name, role_label, today_line, tomorrow_hint, hours_hint)


async def get_people(day, user_id, month=None, year=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year
    max_day = calendar.monthrange(year, month)[1]

    if day > max_day:
        return "Такой даты в этом месяце нет."

    my_status = await get_my_status_for_day(user_id, day, month, year)

    if not is_day_published(day, month, year):
        return (
            mf.who_works_card(
                format_date(day, month, year),
                my_status,
                [],
            )
            + "\n\n📭 График на этот период пока не составлен."
        )

    result = await get_people_for_day(day, month, year)

    role_blocks = [
        (role_display_label(role_key), len(people), people)
        for role_key in ordered_role_keys(result)
        for people in [result.get(role_key, [])]
    ]

    return mf.who_works_card(format_date(day, month, year), my_status, role_blocks)

async def find_next_shift(name, from_day, from_month=None, from_year=None, target_role=None):
    """Ищет следующую смену начиная с from_day, переходит через месяц если нужно."""
    now = now_local()
    if from_month is None:
        from_month = now.month
    if from_year is None:
        from_year = now.year

    # Смотрим вперёд на 45 дней максимум
    from datetime import date
    start = date(from_year, from_month, from_day)

    for offset in range(1, 46):
        target = start + timedelta(days=offset)
        d, m, y = target.day, target.month, target.year

        if not is_day_published(d, m, y):
            continue

        try:
            row, _ = await find_row(name, d, m, y, target_role=target_role)
            if not row:
                continue
            value = await get_day_value(row, d, m, y)
            if is_work_shift(value):
                return target, value
        except ValueError:
            continue

    return None, None

async def get_notification_text(name, target_role=None):
    now = now_local()
    today = now.day
    month = now.month
    year = now.year

    if not is_day_published(today, month, year):
        next_dt, next_value = await find_next_shift(name, today, month, year, target_role=target_role)
        if next_dt:
            from datetime import date
            today_date = date(year, month, today)
            off_days = (next_dt - today_date).days
            return (
                f"🔔 Ежедневное уведомление\n\n"
                f"{name}\n"
                f"{format_date(today, month, year)}\n"
                f"📋 График пока не составлен\n\n"
                f"Ближайшая смена: {format_date(next_dt.day, next_dt.month, next_dt.year)} — {detect_shift(next_value)}\n"
                f"До неё: {off_days} дн."
            )
        return None

    row, _ = await find_row(name, today, month, year, target_role=target_role)
    if not row:
        return None

    value = await get_day_value(row, today, month, year)

    if is_work_shift(value):
        people_by_role = await get_people_for_day(today, month, year)
        total = sum(len(v) for v in people_by_role.values())
        return (
            f"🔔 Ежедневное уведомление\n\n"
            f"{name}\n"
            f"{format_date(today, month, year)}\n"
            f"✅ Сегодня ты работаешь: {detect_shift(value)}\n"
            f"👥 На смене: {total} чел."
        )

    next_dt, next_value = await find_next_shift(name, today, month, year, target_role=target_role)
    common_off = await get_common_day_off_people(name, today, month, year)

    text = (
        f"🔔 Ежедневное уведомление\n\n"
        f"{name}\n"
        f"{format_date(today, month, year)}\n"
        f"🏖 Сегодня ты отдыхаешь"
    )

    if next_dt:
        from datetime import date
        today_date = date(year, month, today)
        off_days = (next_dt - today_date).days
        text += (
            f"\n\nДо ближайшей смены: {off_days} дн.\n"
            f"Ближайшая смена: {format_date(next_dt.day, next_dt.month, next_dt.year)} — {detect_shift(next_value)}"
        )
    else:
        text += "\n\nБлижайшей смены в актуальном графике пока нет."

    if common_off:
        text += "\n\n🏖 Сегодня вместе с тобой отдыхают:\n" + "\n".join(common_off)

    return text
