"""Detect sheet name changes and ask admin to confirm before updating users.name."""

from __future__ import annotations

import logging

from departments_manager import ALL_NAMES, DEPARTMENTS
from repositories.name_rename_repo import create_pending, list_pending
from repositories.users_repo import get_registered_users
from services.admin_notify import notify_admins
from services.schedule_service import (
    clean_person_name,
    person_names_match,
    preferred_sheet_name,
)

# Avoid re-sending Telegram alert for the same key in-process.
_notified_keys: set[str] = set()


def rename_confirm_markup(request_id: int) -> dict:
    return {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Да, тот же человек",
                    "callback_data": f"rename:ok:{request_id}",
                },
                {
                    "text": "❌ Нет",
                    "callback_data": f"rename:no:{request_id}",
                },
            ]
        ]
    }


def _format_rename_alert(
    request_id: int,
    user_id: int,
    old_name: str,
    new_name: str,
    role: str | None,
) -> str:
    role_line = f"\nРоль: {role}" if role else ""
    return (
        "✏️ Имя в таблице изменилось\n\n"
        f"Было: {old_name}\n"
        f"Стало: {new_name}"
        f"{role_line}\n"
        f"user_id: `{user_id}`\n\n"
        "Это один и тот же человек?\n"
        "Пока не подтвердишь — имя в боте не меняется."
    )


async def propose_name_rename(
    user_id: int,
    old_name: str,
    new_name: str,
    role: str | None = None,
    *,
    notify: bool = True,
) -> int | None:
    """Create pending rename + notify admin. Returns request id or None."""
    old = (old_name or "").replace("\xa0", " ").strip()
    new = clean_person_name(new_name)
    if not user_id or not old or not new or old == new:
        return None

    request_id = await create_pending(user_id, old, new, role)
    if not request_id:
        return None

    notify_key = f"req:{request_id}"
    if notify and notify_key not in _notified_keys:
        text = _format_rename_alert(request_id, user_id, old, new, role)
        sent = await notify_admins(text, reply_markup=rename_confirm_markup(request_id))
        if sent:
            _notified_keys.add(notify_key)
            logging.info(
                "name_rename proposed id=%s user_id=%s %r → %r",
                request_id, user_id, old, new,
            )
        else:
            logging.warning(
                "name_rename proposed id=%s but admin notify failed",
                request_id,
            )
    return request_id


def _sheet_names_for_role(role: str | None) -> list[str]:
    if not role:
        return list(ALL_NAMES)
    # DEPARTMENTS keys are emoji labels; values are names. Role in users is plain.
    from departments_manager import role_display_label

    label = role_display_label(role) if role else None
    names: list[str] = []
    if label and label in DEPARTMENTS:
        names.extend(DEPARTMENTS[label])
    # Also try plain role keys / any dept containing role text.
    for dep_label, dep_names in DEPARTMENTS.items():
        if role and role in dep_label:
            names.extend(dep_names)
    if names:
        # unique keep order
        seen: set[str] = set()
        out = []
        for n in names:
            if n not in seen:
                seen.add(n)
                out.append(n)
        return out
    return list(ALL_NAMES)


def _fuzzy_candidates(bot_name: str, role: str | None) -> list[str]:
    pool = _sheet_names_for_role(role)
    hits = []
    for sheet_name in pool:
        preferred = preferred_sheet_name(bot_name, sheet_name)
        if preferred:
            hits.append(preferred)
        elif person_names_match(bot_name, sheet_name):
            cleaned = clean_person_name(sheet_name)
            if cleaned and cleaned != bot_name:
                hits.append(cleaned)
    # unique
    seen: set[str] = set()
    out = []
    for n in hits:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


async def scan_registered_name_renames() -> dict:
    """
    Compare registered users.name with current sheet roster.
    Propose renames when exactly one fuzzy candidate appears.
    Alert when name vanished with no candidate.
    """
    users = await get_registered_users()
    sheet_exact = {str(n).strip() for n in ALL_NAMES if n}
    proposed = 0
    missing = 0
    multi = 0

    for row in users:
        user_id = int(row[0])
        name = (row[1] or "").strip() if len(row) > 1 else ""
        role = row[2] if len(row) > 2 else None
        account_type = row[3] if len(row) > 3 else "staff"
        if not name:
            continue
        if str(account_type) == "supervisor":
            continue
        if name in sheet_exact:
            continue

        candidates = _fuzzy_candidates(name, role)
        if len(candidates) == 1:
            req = await propose_name_rename(user_id, name, candidates[0], role)
            if req:
                proposed += 1
        elif len(candidates) > 1:
            multi += 1
            text = (
                "⚠️ Имя пропало из таблицы, несколько похожих\n\n"
                f"В боте: {name}\n"
                f"user_id: `{user_id}`\n"
                f"Роль: {role or '—'}\n\n"
                "Кандидаты:\n"
                + "\n".join(f"• {c}" for c in candidates[:8])
                + "\n\nИсправь имя в карточке пользователя вручную."
            )
            cache_key = f"multi:{user_id}:{name}"
            if cache_key not in _notified_keys:
                await notify_admins(text)
                _notified_keys.add(cache_key)
        else:
            missing += 1
            cache_key = f"missing:{user_id}:{name}"
            if cache_key not in _notified_keys:
                await notify_admins(
                    "🚨 Имя пользователя не найдено в таблице\n\n"
                    f"В боте: {name}\n"
                    f"user_id: `{user_id}`\n"
                    f"Роль: {role or '—'}\n\n"
                    "Похожих имён нет. Проверь лист или карточку пользователя."
                )
                _notified_keys.add(cache_key)

    for pending in await list_pending(20):
        req_id = int(pending[0])
        notify_key = f"req:{req_id}"
        if notify_key in _notified_keys:
            continue
        user_id = int(pending[1])
        old_name = pending[2]
        new_name = pending[3]
        role = pending[4] if len(pending) > 4 else None
        text = _format_rename_alert(req_id, user_id, old_name, new_name, role)
        sent = await notify_admins(text, reply_markup=rename_confirm_markup(req_id))
        if sent:
            _notified_keys.add(notify_key)

    return {
        "proposed": proposed,
        "missing": missing,
        "ambiguous": multi,
    }
