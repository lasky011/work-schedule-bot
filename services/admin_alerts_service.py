"""Дедупликация и отправка алертов администраторам."""

from __future__ import annotations

import logging

from app_config import now_local
from services.admin_health_service import collect_health_issues, format_health_report
from services.admin_notify import notify_admins

_active_issues: dict[str, str] = {}
_repeat_after_seconds = 3600
_last_repeat: dict[str, object] = {}


def reset_alert_state() -> None:
    _active_issues.clear()
    _last_repeat.clear()


async def run_health_alerts() -> dict:
    """Проверяет систему и шлёт алерты/восстановления. Возвращает сводку."""
    issues = collect_health_issues()
    current = {key: message for key, message in issues}
    sent_new = 0
    sent_resolved = 0
    now = now_local()

    for key in set(_active_issues) - set(current):
        text = f"✅ Восстановлено: {_active_issues[key]}"
        sent_resolved += await notify_admins(text)
        _active_issues.pop(key, None)
        _last_repeat.pop(key, None)

    for key, message in current.items():
        should_send = False
        if key not in _active_issues:
            should_send = True
        elif _active_issues[key] != message:
            should_send = True
        else:
            last = _last_repeat.get(key)
            if last is None or (now - last).total_seconds() >= _repeat_after_seconds:
                should_send = True

        if should_send:
            text = f"🚨 {message}"
            count = await notify_admins(text)
            if count:
                sent_new += count
                _active_issues[key] = message
                _last_repeat[key] = now
                logging.warning("admin alert sent: %s", message)

    return {
        "issues": issues,
        "active_count": len(current),
        "sent_new": sent_new,
        "sent_resolved": sent_resolved,
        "report": format_health_report(issues),
    }
