"""Google Sheets: поиск смен, форматирование графика."""

import calendar
import logging
import re
from datetime import date, datetime, timedelta

from app_config import now_local
from services.sheet_periods_service import SHEET_GID_MAP
from departments_manager import (
    DEPT_EMOJIS,
    SHEET_ROLES,
    normalize_role_name,
    ordered_role_keys,
    role_display_label,
)
from schedule_utils import clean_value, detect_shift, format_date, is_work_shift
from repositories.users_repo import get_user

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
        return f"✅ Ты работаешь: {detect_shift(value)}"

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
        return f"{name}\n\n{format_date(day, month, year)} — график пока не составлен"

    row, role = await find_row(name, day, month, year, target_role=target_role)

    if not row:
        return f"Не нашёл график для: {name}"

    role_text = f"\n{DEPT_EMOJIS.get(role, role)}" if role else ""
    value = await get_day_value(row, day, month, year)
    if is_work_shift(value):
        header = f"{format_date(day, month, year)} — {name} работает ✅"
        shift_line = f"Смена: {detect_shift(value)}"
    else:
        header = f"{format_date(day, month, year)} — {name} отдыхает 🏖"
        shift_line = ""

    role_suffix = role_text.strip() if role_text else ""
    text = header
    if role_suffix:
        text += f"  ({role_suffix})"
    if shift_line:
        text += f"\n{shift_line}"

    people_by_role = await get_people_for_day(day, month, year)
    coworkers_parts = []
    for role_key in ordered_role_keys(people_by_role):
        people = people_by_role.get(role_key, [])
        if not people:
            continue
        coworkers_parts.append(role_display_label(role_key))
        coworkers_parts.extend(people)
        coworkers_parts.append("")
    coworkers_text = "\n".join(coworkers_parts).strip()
    total_on_shift = sum(len(v) for v in people_by_role.values())
    if coworkers_text:
        text += f"\n\n👥 {format_date(day, month, year)} работают: всего {total_on_shift}\n\n" + coworkers_text.strip()

    if not is_work_shift(value):
        common_off = await get_common_day_off_people(name, day, month, year)
        if common_off:
            text += f"\n\n🏖 {format_date(day, month, year)} вместе отдыхают:\n" + "\n".join(unique_keep_order(common_off))

    return text


async def get_range_schedule(name, start_day, end_day, month=None, year=None, target_role=None):
    now = now_local()
    if month is None:
        month = now.month
    if year is None:
        year = now.year

    max_day = calendar.monthrange(year, month)[1]
    end_day = min(end_day, max_day)

    result = [name]
    saved_role = None
    found_any = False
    role_line_index = None
    unpublished_start = None

    for day in range(start_day, end_day + 1):
        if not is_day_published(day, month, year):
            if unpublished_start is None:
                unpublished_start = day
            continue

        if unpublished_start is not None:
            if role_line_index is None:
                result.append("")
                role_line_index = 1
                result.append("")
            if unpublished_start == day - 1:
                result.append(f"{unpublished_start} {MONTHS[month]} — график пока не составлен")
            else:
                result.append(f"{unpublished_start}–{day - 1} {MONTHS[month]} — график пока не составлен")
            unpublished_start = None

        row, role = await find_row(name, day, month, year, target_role=target_role)

        if row:
            found_any = True
            if role:
                saved_role = role
            value = await get_day_value(row, day, month, year)
        else:
            value = ""

        if role_line_index is None:
            result.append(DEPT_EMOJIS.get(saved_role or role or '', saved_role or role or ''))
            role_line_index = 1
            result.append("")

        result.append(f"{format_date(day, month, year)} — {detect_shift(value)}")

    if unpublished_start is not None:
        if role_line_index is None:
            result.append(DEPT_EMOJIS.get(saved_role or '', saved_role or ''))
            role_line_index = 1
            result.append("")
        if unpublished_start == end_day:
            result.append(f"{unpublished_start} {MONTHS[month]} — график пока не составлен")
        else:
            result.append(f"{unpublished_start}–{end_day} {MONTHS[month]} — график пока не составлен")

    if not found_any:
        return f"Не нашёл график для: {name}"

    if saved_role and role_line_index is not None:
        result[role_line_index] = DEPT_EMOJIS.get(saved_role, saved_role)

    return "\n".join(result)


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
        return f"👥 {format_date(day, month, year)}\n\n{my_status}\n\nГрафик на этот период пока не составлен."

    result = await get_people_for_day(day, month, year)

    total = sum(len(v) for v in result.values())
    text = f"👥 {format_date(day, month, year)} работают: всего {total}\n\n"
    text += my_status + "\n\n"

    has_any = False
    for role_key in ordered_role_keys(result):
        people = result.get(role_key, [])
        if people:
            has_any = True
            label = role_display_label(role_key)
            text += f"{label} ({len(people)})\n" + "\n".join(people) + "\n\n"

    if not has_any:
        text += "Никто не работает."

    return text.strip()

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
