import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import jwt
from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app.api.api_o1.routes import api_router
from app.api.deps import AuthContext
from app.core.config import settings
from app.core.database.session import SessionLocal
from app.core.exceptions import AppException
from app.core.logging import configure_logging
from app.models.order_models import Job, JobLocationLog
from app.realtime.tracking_hub import tracking_hub
from app.services.operations import assert_job_view, _status_str
from decimal import Decimal
import uuid


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(os.path.abspath(settings.LOCAL_UPLOAD_DIR), exist_ok=True)
    yield


def create_app() -> FastAPI:
    configure_logging()
    upload_dir = os.path.abspath(settings.LOCAL_UPLOAD_DIR)
    os.makedirs(upload_dir, exist_ok=True)
    os.makedirs(os.path.join(upload_dir, "jobs"), exist_ok=True)

    app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan)

    @app.exception_handler(AppException)
    async def app_exc(_request: Request, exc: AppException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message})

    app.include_router(api_router, prefix="/api/o1")
    app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "service": settings.APP_NAME}

    @app.websocket("/ws/jobs/{job_id}/tracking")
    async def ws_tracking(
        websocket: WebSocket,
        job_id: str,
        token: str | None = Query(None),
    ) -> None:
        if not token or not settings.JWT_SECRET_KEY.strip():
            await websocket.close(code=4401)
            return
        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
        except jwt.PyJWTError:
            await websocket.close(code=4401)
            return
        if payload.get("typ") != "access":
            await websocket.close(code=4401)
            return
        sub = payload.get("sub")
        if not sub:
            await websocket.close(code=4401)
            return
        ctx = AuthContext(
            user_id=str(sub),
            role_id=str(payload["role_id"]) if payload.get("role_id") else None,
            role_type=str(payload.get("role_type") or ""),
            hub_id=str(payload["hub_id"]) if payload.get("hub_id") else None,
        )

        def _authorize_and_snapshot():
            db = SessionLocal()
            try:
                assert_job_view(db, job_id, ctx)
                return tracking_hub.get_redis_latest(job_id)
            finally:
                db.close()

        try:
            snap = await run_in_threadpool(_authorize_and_snapshot)
        except AppException:
            await websocket.close(code=4403)
            return

        await tracking_hub.connect(job_id, websocket)
        if snap:
            try:
                await websocket.send_json(snap)
            except Exception:
                pass
        try:
            while True:
                data = await websocket.receive_json()
                if "lat" not in data or "lng" not in data:
                    continue
                agent_id = str(data.get("agent_id") or ctx.user_id)

                def _persist():
                    db = SessionLocal()
                    try:
                        job = db.query(Job).filter(Job.job_id == job_id).first()
                        if job is None:
                            return None
                        if ctx.role_type != "admin":
                            if ctx.user_id != agent_id:
                                return None
                            if job.agent_id and str(job.agent_id) != agent_id:
                                return None
                        cap = datetime.now(timezone.utc)
                        log = JobLocationLog(
                            log_id=str(uuid.uuid4()),
                            job_id=job_id,
                            agent_id=agent_id,
                            lat=Decimal(str(data["lat"])),
                            lng=Decimal(str(data["lng"])),
                            heading=Decimal(str(data["heading"])) if data.get("heading") is not None else None,
                            speed_kmh=Decimal(str(data["speed_kmh"])) if data.get("speed_kmh") is not None else None,
                            captured_at=cap,
                        )
                        db.add(log)
                        db.commit()
                        out = {
                            "lat": float(data["lat"]),
                            "lng": float(data["lng"]),
                            "heading": data.get("heading"),
                            "speed_kmh": data.get("speed_kmh"),
                            "agent_name": str(data.get("agent_name") or ""),
                            "job_status": _status_str(job.status),
                            "timestamp": cap.isoformat(),
                        }
                        tracking_hub.set_redis_latest(job_id, out)
                        return out
                    finally:
                        db.close()

                out = await run_in_threadpool(_persist)
                if out:
                    await tracking_hub.broadcast(job_id, out)
        except WebSocketDisconnect:
            pass
        finally:
            await tracking_hub.disconnect(job_id, websocket)

    return app


app = create_app()
