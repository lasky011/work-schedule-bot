"""Сбор проблем инфраструктуры для admin-алертов."""

from __future__ import annotations

from app_config import now_local
from db import get_db_connection
from departments_manager import get_departments_status
from services.period_coverage_service import format_period_key, missing_period_keys
from services.sheet_periods_service import SHEET_GID_MAP
from services.sheet_loader import oldest_cache_age_seconds
from sheets_client import cached_df, cached_time

CACHE_STALE_SECONDS = 3600


def collect_health_issues() -> list[tuple[str, str]]:
    """Возвращает список (ключ, описание) активных проблем."""
    issues: list[tuple[str, str]] = []

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        conn.close()
    except Exception as e:
        issues.append(("db", f"БД недоступна: {e}"))
        return issues

    if not SHEET_GID_MAP:
        issues.append(("periods", "В БД нет периодов графика (SHEET_GID_MAP пуст)"))

    missing = missing_period_keys(days_ahead=10)
    if missing:
        labels = ", ".join(format_period_key(key) for key in missing[:3])
        extra = f" (+{len(missing) - 3})" if len(missing) > 3 else ""
        issues.append((
            "period_gap",
            f"Нет gid для ближайших периодов: {labels}{extra}",
        ))

    unique_gids = sorted({int(gid) for gid in SHEET_GID_MAP.values()})
    if unique_gids and not cached_df:
        issues.append(("cache_empty", "Кэш Google Sheets пуст при наличии периодов"))

    if cached_time:
        oldest = oldest_cache_age_seconds()
        if oldest is not None and oldest > CACHE_STALE_SECONDS:
            issues.append((
                "cache_stale",
                f"Кэш листов устарел (порог {CACHE_STALE_SECONDS // 60} мин., сейчас {oldest // 60} мин.)",
            ))

    if unique_gids:
        probe_gid = unique_gids[0]
        if probe_gid not in cached_df:
            issues.append(("sheets_probe", f"Лист gid={probe_gid} не в кэше"))

    departments = get_departments_status()
    if cached_df and not departments.get("loaded"):
        issues.append(("departments", "Отделы не загружены при наличии кэша листов"))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE name IS NOT NULL AND name != ''"
        )
        registered = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM schedule_snapshots")
        snapshots = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        missing = max(0, int(registered) - int(snapshots))
        if registered >= 5 and missing >= 3:
            issues.append((
                "snapshots",
                f"Без snapshot: {missing} из {registered} зарегистрированных",
            ))
    except Exception:
        pass

    return issues


def format_health_report(issues: list[tuple[str, str]]) -> str:
    if not issues:
        return "✅ Критичных проблем не найдено."
    lines = ["🚨 Проблемы системы:\n"]
    for _key, message in issues:
        lines.append(f"• {message}")
    return "\n".join(lines)
