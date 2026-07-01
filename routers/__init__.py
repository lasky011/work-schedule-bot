from routers.admin import router as admin_router
from routers.colleagues import router as colleagues_router
from routers.common import router as common_router
from routers.fallback import router as fallback_router
from routers.salary import router as salary_router
from routers.schedule import router as schedule_router
from routers.settings import router as settings_router

__all__ = [
    "admin_router",
    "common_router",
    "settings_router",
    "schedule_router",
    "salary_router",
    "colleagues_router",
    "fallback_router",
]
