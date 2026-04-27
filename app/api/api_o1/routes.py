from fastapi import APIRouter

from app.api.api_o1.endpoints import o1

api_router = APIRouter()
api_router.include_router(o1.router)
