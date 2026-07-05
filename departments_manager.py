import logging
from typing import Awaitable, Callable

from app_config import now_local
from schedule_utils import clean_value

SHEET_ROLES = ["Менеджеры", "Менеджер", "Официант", "Бармен", "Кальян", "Хостес"]

ROLE_ORDER = ["Менеджеры", "Менеджер", "Официант", "Бармен", "Кальян", "Кальянщик", "Хостес"]

DEPARTMENTS_FALLBACK: dict[str, list[str]] = {
    "👔 Менеджер": [
        "Рина Евгеньевна",
        "Нодира Комилджоновна",
        "Вадим Вячеславович",
    ],
    "🍽 Официант": [
        "Виталий",
        "Платон",
        "Юлия",
        "Владислав",
        "Злата",
        "Егор Капустин",
        "Егор Корниенков",
        "Кристина (наличка)",
    ],
    "🍸 Бармен": [
        "Вениамин",
        "Дарья",
    ],
    "💨 Кальян": [
        "Александр",
        "Никита Рафаэлович",
        "Дмитрий",
        "Андрей",
    ],
    "🙋 Хостес": [
        "Татьяна",
        "Мария",
        "Екатерина",
        "Дарья",
    ],
}

DEPT_EMOJIS: dict[str, str] = {
    "Менеджер": "👔 Менеджер",
    "Официант": "🍽 Официант",
    "Бармен": "🍸 Бармен",
    "Кальян": "💨 Кальян",
    "Хостес": "🙋 Хостес",
}

DEPARTMENTS: dict[str, list[str]] = {}
ALL_NAMES: list[str] = []

_departments_updated_at = None
_DEPARTMENTS_TTL_SEC = 300
_clean_person_name = None
_sheet_loader: Callable[..., Awaitable] | None = None


def configure_departments_manager(clean_person_name_fn, sheet_loader):
    global _clean_person_name, _sheet_loader
    _clean_person_name = clean_person_name_fn
    _sheet_loader = sheet_loader
    _apply_departments({k: list(v) for k, v in DEPARTMENTS_FALLBACK.items()})


def _apply_departments(new_departments: dict[str, list[str]]) -> None:
    DEPARTMENTS.clear()
    DEPARTMENTS.update(new_departments)
    ALL_NAMES.clear()
    ALL_NAMES.extend(name for names in DEPARTMENTS.values() for name in names)


def is_department_label(text: str | None) -> bool:
    return resolve_department_label(text) is not None


def resolve_department_label(text: str | None) -> str | None:
    if text is None:
        return None
    if text in DEPARTMENTS:
        return text

    target_role = normalize_role_name(_role_from_department_label(text))
    if not target_role:
        return None
    for dep_label in DEPARTMENTS:
        if normalize_role_name(_role_from_department_label(dep_label)) == target_role:
            return dep_label
    return None


def is_person_name(text: str | None) -> bool:
    return text is not None and text in ALL_NAMES


def _role_from_department_label(dep_label: str) -> str:
    parts = dep_label.split(" ", 1)
    return parts[1] if len(parts) == 2 else dep_label


def roles_for_person(name: str | None) -> list[str]:
    """Роли/отделы, в которых встречается имя (порядок как в DEPARTMENTS)."""
    if not name:
        return []

    roles = []
    for dep_label, names in DEPARTMENTS.items():
        if name in names:
            roles.append(_role_from_department_label(dep_label))
    return roles


def person_has_ambiguous_role(name: str | None) -> bool:
    return len(roles_for_person(name)) > 1


def normalize_role_name(role: str | None) -> str | None:
    """Приводит роли из кнопок и Google Sheets к одному виду."""
    if role is None:
        return None

    text = str(role).replace("\xa0", " ").strip()
    if not text:
        return None

    aliases = {
        "Менеджер": "Менеджеры",
        "Менеджеры": "Менеджеры",
        "Официант": "Официант",
        "Официанты": "Официант",
        "Бармен": "Бармен",
        "Бармены": "Бармен",
        "Кальянщик": "Кальян",
        "Кальянщики": "Кальян",
        "Кальян": "Кальян",
        "Хостес": "Хостес",
    }

    return aliases.get(text, text)


def role_display_label(role: str) -> str:
    """Красивое название роли/подразделения для вывода."""
    if not role:
        return ""

    role = str(role).strip()
    display_role = normalize_role_name(role) or role

    emoji_map = {
        "Менеджеры": "👔 Менеджеры",
        "Официант": "🍽 Официант",
        "Бармен": "🍸 Бармен",
        "Кальян": "💨 Кальян",
        "Хостес": "🙋 Хостес",
    }

    return emoji_map.get(display_role, DEPT_EMOJIS.get(display_role, DEPT_EMOJIS.get(role, role)))


def get_departments_status() -> dict[str, object]:
    updated_at = _departments_updated_at.isoformat() if _departments_updated_at else None
    age_seconds = None
    if _departments_updated_at is not None:
        try:
            age_seconds = max(0, int((now_local() - _departments_updated_at).total_seconds()))
        except Exception:
            age_seconds = None

    return {
        "loaded": bool(DEPARTMENTS),
        "department_count": len(DEPARTMENTS),
        "person_count": len(ALL_NAMES),
        "fallback_active": _departments_updated_at is None,
        "updated_at": updated_at,
        "age_seconds": age_seconds,
    }


def ordered_role_keys(people_by_role: dict) -> list:
    """Роли в стабильном порядке: сначала основные из таблицы, потом остальные."""
    keys = list(people_by_role.keys())
    result = []

    for role in ROLE_ORDER:
        if role in people_by_role and role not in result:
            result.append(role)

    for role in keys:
        if role not in result:
            result.append(role)

    return result


def parse_departments(df) -> dict:
    result: dict[str, list[str]] = {}
    current_role = None
    for i in range(len(df)):
        first = str(df.iloc[i, 0]).strip()
        if first in SHEET_ROLES:
            current_role = first
            result[current_role] = []
            continue
        if current_role is None:
            continue
        name = clean_value(first)
        if name:
            result[current_role].append(_clean_person_name(name))
    return result


async def refresh_departments(force: bool = False) -> None:
    global _departments_updated_at

    if _sheet_loader is None or _clean_person_name is None:
        logging.warning("refresh_departments: departments_manager не настроен")
        return

    now = now_local()
    if (
        not force
        and _departments_updated_at is not None
        and (now - _departments_updated_at).total_seconds() < _DEPARTMENTS_TTL_SEC
    ):
        return

    try:
        df = await _sheet_loader(now.day)
        parsed = parse_departments(df)
        if not parsed:
            logging.warning("refresh_departments: пустой результат, оставляю fallback")
            return

        emoji_map = {label.split(" ", 1)[1]: label for label in DEPARTMENTS_FALLBACK}
        emoji_map["Менеджеры"] = "👔 Менеджер"
        emoji_map["Кальянщик"] = "💨 Кальян"

        new_departments = {
            emoji_map.get(role, role): names
            for role, names in parsed.items()
            if names
        }
        _apply_departments(new_departments)
        _departments_updated_at = now
        logging.info(
            "refresh_departments: %d ролей, %d сотрудников",
            len(DEPARTMENTS),
            len(ALL_NAMES),
        )
    except (ValueError, ConnectionError) as e:
        logging.warning("refresh_departments: ошибка (%s), fallback активен", e)
    except Exception as e:
        logging.error("refresh_departments: неожиданная ошибка: %s", e)
