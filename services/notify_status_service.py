"""Аудит рассылок (сводка админам после «написать команде»)."""

from __future__ import annotations

import logging

from app_config import NOTIFY_DRY_RUN, now_local
from services.admin_notify import notify_admins


def _short_error(err: str | None) -> str:
    if not err:
        return "unknown"
    text = str(err)
    low = text.lower()
    if "blocked by the user" in low:
        return "заблокировал бота"
    if "chat not found" in low:
        return "нет /start"
    if "deactivated" in low:
        return "аккаунт удалён"
    if "too many requests" in low:
        return "flood limit"
    return text[:80]


def format_delivery_report(
    *,
    kind: str,
    sender: str | None,
    audience: str | None,
    total: int,
    sent: int,
    failed: int,
    failed_items: list[tuple[str, str | None]] | None = None,
    dry_run: bool = False,
    preview: str | None = None,
) -> str:
    now = now_local().strftime("%d.%m.%Y %H:%M")
    lines = [
        f"📬 {kind}",
        f"Время: {now}",
    ]
    if dry_run or NOTIFY_DRY_RUN:
        lines.append("⚠ DRY RUN — пользователям не отправлялось")
    if sender:
        lines.append(f"От кого: {sender}")
    if audience:
        lines.append(f"Аудитория: {audience}")
    lines.append(f"Выбрано: {total}")
    lines.append(f"Доставлено: {sent}")
    lines.append(f"Не дошло: {failed}")
    if preview:
        clipped = preview.strip().replace("\n", " ")
        if len(clipped) > 120:
            clipped = clipped[:117] + "…"
        lines.append(f"Текст: {clipped}")
    if failed_items:
        lines.append("")
        lines.append("Не доставлено:")
        for name, err in failed_items[:25]:
            lines.append(f"• {name} — {_short_error(err)}")
        if len(failed_items) > 25:
            lines.append(f"… и ещё {len(failed_items) - 25}")
    return "\n".join(lines)


async def report_delivery_to_admins(**kwargs) -> int:
    text = format_delivery_report(**kwargs)
    logging.info("notify_audit:\n%s", text)
    try:
        return await notify_admins(text)
    except Exception:
        logging.exception("notify_audit: не удалось отправить сводку админам")
        return 0
