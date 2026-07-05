"""FastAPI приложение Mini App."""

import os
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api.auth import InitDataError, validate_init_data
from app_config import (
    APP_TIMEZONE_NAME,
    BOT_TOKEN,
    MINIAPP_ENABLED,
    MINIAPP_PORT,
    SHEET_PERIODS_REFRESH_SECONDS,
    now_local,
)
from db import USE_POSTGRES, get_db_connection
from departments_manager import get_departments_status
from services import miniapp_service
from services.schedule_watch_service import WATCH_DAYS
from services.sheet_periods_service import SHEET_GID_MAP
from sheets_client import cache_locks, cached_df, cached_time

APP_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent.parent / "miniapp" / "static"
MINIAPP_ASSETS = (
    "app.css",
    "core/config.js",
    "core/telegram.js",
    "core/api.js",
    "core/dom.js",
    "app.js",
)


def _asset_version(name: str) -> str:
    path = STATIC_DIR / name
    try:
        return str(int(path.stat().st_mtime))
    except OSError:
        return "1"


def _safe_mtime_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=now_local().tzinfo).isoformat()
    except OSError:
        return None


def _revision_hint() -> str | None:
    for env_name in ("RELEASE_VERSION", "SOURCE_VERSION", "GIT_SHA", "COMMIT_SHA", "FLY_IMAGE_REF"):
        value = (os.getenv(env_name) or "").strip()
        if value:
            if env_name == "FLY_IMAGE_REF":
                value = value.rsplit("@", 1)[0]
                value = value.rsplit(":", 1)[-1]
            return value[:40]

    git_dir = APP_ROOT / ".git"
    head_file = git_dir / "HEAD"
    try:
        head_value = head_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    if head_value.startswith("ref: "):
        ref_path = git_dir / head_value[5:]
        try:
            return ref_path.read_text(encoding="utf-8").strip()[:12]
        except OSError:
            return None
    return head_value[:12] or None


def _query_count(cursor, query: str) -> int | None:
    try:
        cursor.execute(query)
        row = cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return None


def _db_health() -> dict[str, object]:
    backend = "postgres" if USE_POSTGRES else "sqlite"
    result: dict[str, object] = {
        "backend": backend,
        "ok": False,
        "registered_users": None,
        "notify_enabled": None,
        "notify_hours_enabled": None,
        "schedule_snapshots": None,
    }

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        result["ok"] = True
        result["registered_users"] = _query_count(
            cursor,
            "SELECT COUNT(*) FROM users WHERE name IS NOT NULL AND name != ''",
        )
        result["notify_enabled"] = _query_count(cursor, "SELECT COUNT(*) FROM users WHERE notify=1")
        result["notify_hours_enabled"] = _query_count(
            cursor,
            "SELECT COUNT(*) FROM users WHERE notify_hours=1",
        )
        result["schedule_snapshots"] = _query_count(cursor, "SELECT COUNT(*) FROM schedule_snapshots")
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    return result


def _sheets_health() -> dict[str, object]:
    ages: list[int] = []
    now = now_local()
    for ts in cached_time.values():
        try:
            ages.append(max(0, int((now - ts).total_seconds())))
        except Exception:
            continue

    return {
        "configured_periods": len(SHEET_GID_MAP),
        "cache_entries": len(cached_df),
        "cache_locks": len(cache_locks),
        "oldest_cache_age_seconds": max(ages) if ages else None,
    }


class ShiftLogBody(BaseModel):
    date: str
    hours: float = Field(gt=0, le=24)
    is_standard: bool = True


class ColleagueRef(BaseModel):
    name: str
    role: str | None = None


class CompareBody(BaseModel):
    colleagues: list[ColleagueRef]
    year: int
    month: int
    start: int = Field(ge=1, le=31)
    end: int = Field(ge=1, le=31)


class SettingsPatch(BaseModel):
    notify: bool | None = None
    notify_time: str | None = None
    track_hours: bool | None = None
    notify_hours: bool | None = None
    theme: str | None = None


class ProfilePatch(BaseModel):
    name: str
    role: str


async def get_user_id(x_telegram_init_data: str | None = Header(default=None)) -> int:
    if not x_telegram_init_data:
        raise HTTPException(status_code=401, detail="Требуется авторизация Telegram")
    try:
        data = validate_init_data(x_telegram_init_data, BOT_TOKEN or "")
        return data["user_id"]
    except InitDataError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e


def create_app() -> FastAPI:
    app = FastAPI(title="TNG Alice Mini App", docs_url=None, redoc_url=None)

    @app.get("/api/health")
    async def health():
        db = _db_health()
        departments = get_departments_status()
        sheets = _sheets_health()
        static_ready = STATIC_DIR.is_dir()

        ready = {
            "db": bool(db["ok"]),
            "sheet_periods": sheets["configured_periods"] > 0,
            "departments": bool(departments["loaded"]),
            "static": static_ready,
        }

        return {
            "ok": True,
            "status": "ok" if all(ready.values()) else "degraded",
            "runtime": {
                "service": app.title,
                "fly_app": os.getenv("FLY_APP_NAME"),
                "fly_region": os.getenv("FLY_REGION"),
                "timezone": APP_TIMEZONE_NAME,
                "port_env": os.getenv("PORT"),
                "configured_port": MINIAPP_PORT,
            },
            "build": {
                "revision": _revision_hint(),
                "checked_at": now_local().isoformat(),
                "app_mtime": _safe_mtime_iso(APP_ROOT / "bot.py"),
                "miniapp_index_mtime": _safe_mtime_iso(STATIC_DIR / "index.html"),
            },
            "flags": {
                "miniapp_enabled": MINIAPP_ENABLED,
                "sheet_periods_refresh_seconds": SHEET_PERIODS_REFRESH_SECONDS,
            },
            "ready": ready,
            "deps": {
                "db": db,
                "sheets": sheets,
                "departments": departments,
                "schedule_watch": {
                    "watch_days": WATCH_DAYS,
                    "tracked_users": db.get("schedule_snapshots"),
                },
            },
        }

    @app.get("/api/me")
    async def me(user_id: int = Depends(get_user_id)):
        return await miniapp_service.get_profile(user_id)

    @app.patch("/api/me/settings")
    async def patch_settings(body: SettingsPatch, user_id: int = Depends(get_user_id)):
        data = await miniapp_service.update_user_settings(
            user_id,
            notify=body.notify,
            notify_time=body.notify_time,
            track_hours=body.track_hours,
            notify_hours=body.notify_hours,
            theme=body.theme,
        )
        if data.get("error") == "not_registered":
            raise HTTPException(status_code=403, detail="Сначала выбери имя в боте")
        if data.get("error") == "bad_time":
            raise HTTPException(status_code=400, detail="Неверный формат времени (ЧЧ:ММ)")
        if data.get("error") == "need_time":
            raise HTTPException(status_code=400, detail="Сначала задай время уведомления")
        if data.get("error") == "bad_theme":
            raise HTTPException(status_code=400, detail="Неизвестная тема")
        return data

    @app.get("/api/departments")
    async def departments(_user_id: int = Depends(get_user_id)):
        return miniapp_service.list_departments()

    @app.patch("/api/me/profile")
    async def patch_profile(body: ProfilePatch, user_id: int = Depends(get_user_id)):
        data = await miniapp_service.update_profile(user_id, body.name, body.role)
        if data.get("error") == "bad_name":
            raise HTTPException(status_code=400, detail="Имя не найдено в списке")
        if data.get("error") == "bad_role":
            raise HTTPException(status_code=400, detail="Неверный отдел для этого имени")
        return data

    @app.get("/api/schedule/week")
    async def week_schedule(user_id: int = Depends(get_user_id), offset: int = 0):
        data = await miniapp_service.get_week_schedule(user_id, offset)
        if data.get("error") == "not_registered":
            raise HTTPException(status_code=403, detail="Сначала выбери имя в боте")
        return data

    @app.get("/api/schedule/month")
    async def month_schedule(user_id: int = Depends(get_user_id), offset: int = 0):
        data = await miniapp_service.get_month_schedule(user_id, offset)
        if data.get("error") == "not_registered":
            raise HTTPException(status_code=403, detail="Сначала выбери имя в боте")
        return data

    @app.get("/api/analytics")
    async def analytics(user_id: int = Depends(get_user_id)):
        data = await miniapp_service.get_analytics(user_id)
        if data.get("error") == "not_registered":
            raise HTTPException(status_code=403, detail="Сначала выбери имя в боте")
        return data

    @app.get("/api/team/date")
    async def team_date(_user_id: int = Depends(get_user_id), date: str = ""):
        if not date:
            raise HTTPException(status_code=400, detail="Укажи дату")
        data = await miniapp_service.get_day_roster(date)
        if data.get("error") == "bad_date":
            raise HTTPException(status_code=400, detail="Некорректная дата")
        return data

    @app.get("/api/team/day")
    async def team_day(user_id: int = Depends(get_user_id), offset: int = 0):
        data = await miniapp_service.get_people_on_shift(user_id, offset)
        if data.get("error") == "not_registered":
            raise HTTPException(status_code=403, detail="Сначала выбери имя в боте")
        return data

    @app.get("/api/shifts/day")
    async def shift_day(user_id: int = Depends(get_user_id), date: str = ""):
        if not date:
            raise HTTPException(status_code=400, detail="Укажи дату")
        data = await miniapp_service.get_shift_day_info(user_id, date)
        if data.get("error") == "not_registered":
            raise HTTPException(status_code=403, detail="Сначала выбери имя в боте")
        if data.get("error") == "hours_disabled":
            raise HTTPException(status_code=403, detail="Учёт часов выключен")
        if data.get("error") == "bad_date":
            raise HTTPException(status_code=400, detail="Некорректная дата")
        return data

    @app.post("/api/shifts")
    async def shift_log(body: ShiftLogBody, user_id: int = Depends(get_user_id)):
        data = await miniapp_service.log_shift_hours(
            user_id, body.date, body.hours, is_standard=body.is_standard,
        )
        if data.get("error") == "not_registered":
            raise HTTPException(status_code=403, detail="Сначала выбери имя в боте")
        if data.get("error") == "hours_disabled":
            raise HTTPException(status_code=403, detail="Учёт часов выключен")
        if data.get("error") == "bad_date":
            raise HTTPException(status_code=400, detail="Некорректная дата")
        if data.get("error") == "bad_hours":
            raise HTTPException(status_code=400, detail="Некорректное количество часов")
        return data

    @app.delete("/api/shifts")
    async def shift_delete(user_id: int = Depends(get_user_id), date: str = ""):
        if not date:
            raise HTTPException(status_code=400, detail="Укажи дату")
        data = await miniapp_service.remove_shift_log(user_id, date)
        if data.get("error") == "not_registered":
            raise HTTPException(status_code=403, detail="Сначала выбери имя в боте")
        if data.get("error") == "hours_disabled":
            raise HTTPException(status_code=403, detail="Учёт часов выключен")
        if data.get("error") == "bad_date":
            raise HTTPException(status_code=400, detail="Некорректная дата")
        if data.get("error") == "not_found":
            raise HTTPException(status_code=404, detail="Смена не найдена")
        return data

    @app.get("/api/salary")
    async def salary(
        user_id: int = Depends(get_user_id),
        year: int | None = None,
        month: int | None = None,
        start: int | None = None,
        end: int | None = None,
    ):
        data = await miniapp_service.get_salary(user_id, year, month, start, end)
        if data.get("error") == "not_registered":
            raise HTTPException(status_code=403, detail="Сначала выбери имя в боте")
        return data

    @app.get("/api/salary/periods")
    async def salary_periods(_user_id: int = Depends(get_user_id)):
        return {"periods": miniapp_service.list_compare_periods()}

    @app.get("/api/colleagues")
    async def colleagues(user_id: int = Depends(get_user_id)):
        data = await miniapp_service.get_colleagues(user_id)
        if data.get("error") == "not_registered":
            raise HTTPException(status_code=403, detail="Сначала выбери имя в боте")
        return data

    @app.get("/api/colleagues/week")
    async def colleague_week(
        _user_id: int = Depends(get_user_id),
        name: str = "",
        role: str | None = None,
        offset: int = 0,
    ):
        if not name:
            raise HTTPException(status_code=400, detail="Укажи имя")
        return await miniapp_service.get_colleague_week(name, role, offset)

    @app.get("/api/colleagues/month")
    async def colleague_month(
        _user_id: int = Depends(get_user_id),
        name: str = "",
        role: str | None = None,
        offset: int = 0,
    ):
        if not name:
            raise HTTPException(status_code=400, detail="Укажи имя")
        return await miniapp_service.get_colleague_month(name, role, offset)

    @app.post("/api/colleagues/compare")
    async def colleagues_compare(body: CompareBody, user_id: int = Depends(get_user_id)):
        data = await miniapp_service.compare_with_colleagues(
            user_id,
            [c.model_dump() for c in body.colleagues],
            body.year,
            body.month,
            body.start,
            body.end,
        )
        if data.get("error") == "not_registered":
            raise HTTPException(status_code=403, detail="Сначала выбери имя в боте")
        return data

    @app.get("/api/team")
    async def team(_user_id: int = Depends(get_user_id)):
        return await miniapp_service.get_team_analytics()

    if STATIC_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

        @app.get("/")
        async def index():
            html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
            for asset in MINIAPP_ASSETS:
                html = html.replace(
                    f"/assets/{asset}",
                    f"/assets/{asset}?v={_asset_version(asset)}",
                )
            return HTMLResponse(html, headers={"Cache-Control": "no-store, max-age=0"})

    return app
