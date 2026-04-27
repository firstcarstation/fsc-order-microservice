from __future__ import annotations

import asyncio
import json
from collections import defaultdict

from fastapi import WebSocket

try:
    import redis  # type: ignore
except ImportError:  # pragma: no cover
    redis = None

from app.core.config import settings

_redis = None


def _get_redis():
    global _redis
    if _redis is False:
        return None
    url = settings.REDIS_URL.strip()
    if not url or redis is None:
        _redis = False
        return None
    if _redis is None:
        try:
            _redis = redis.from_url(url, decode_responses=True)
        except Exception:
            _redis = False
            return None
    return _redis


class TrackingHub:
    """In-memory subscribers per job; optional Redis for latest location snapshot."""

    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, job_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._rooms[job_id].add(websocket)

    async def disconnect(self, job_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._rooms[job_id].discard(websocket)
            if not self._rooms[job_id]:
                del self._rooms[job_id]

    def set_redis_latest(self, job_id: str, payload: dict) -> None:
        r = _get_redis()
        if r:
            try:
                r.setex(f"tracking:job:{job_id}", 60, json.dumps(payload))
            except Exception:
                pass

    def get_redis_latest(self, job_id: str) -> dict | None:
        r = _get_redis()
        if not r:
            return None
        try:
            raw = r.get(f"tracking:job:{job_id}")
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        return None

    async def broadcast(self, job_id: str, message: dict) -> None:
        async with self._lock:
            targets = list(self._rooms.get(job_id, ()))
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._rooms[job_id].discard(ws)


tracking_hub = TrackingHub()
