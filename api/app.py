"""FastAPI приложение Mini App."""

from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api.auth import InitDataError, validate_init_data
from app_config import BOT_TOKEN
from services import miniapp_service

STATIC_DIR = Path(__file__).resolve().parent.parent / "miniapp" / "static"


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
        return {"ok": True}

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
        )
        if data.get("error") == "not_registered":
            raise HTTPException(status_code=403, detail="Сначала выбери имя в боте")
        if data.get("error") == "bad_time":
            raise HTTPException(status_code=400, detail="Неверный формат времени (ЧЧ:ММ)")
        if data.get("error") == "need_time":
            raise HTTPException(status_code=400, detail="Сначала задай время уведомления")
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
            return FileResponse(STATIC_DIR / "index.html")

    return app
