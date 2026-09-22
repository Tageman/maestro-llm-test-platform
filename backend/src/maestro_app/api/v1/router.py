from fastapi import APIRouter

from maestro_app.api.v1.routes import generations, health, runs, workbooks


api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(workbooks.router)
api_router.include_router(generations.router)
api_router.include_router(runs.router)
