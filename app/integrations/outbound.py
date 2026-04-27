from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.core.config import settings
from app.core.exceptions import AppException

logger = logging.getLogger(__name__)


def _client() -> httpx.Client:
    return httpx.Client(timeout=settings.HTTP_CLIENT_TIMEOUT_SEC)


def validate_user_remote(user_id: str) -> None:
    base = settings.USER_MS_BASE_URL.strip()
    if not base:
        return
    url = f"{base.rstrip('/')}{settings.USER_MS_INTERNAL_VALIDATE_PATH}"
    headers: dict[str, str] = {}
    if settings.USER_MS_INTERNAL_API_KEY.strip():
        headers["X-Internal-Api-Key"] = settings.USER_MS_INTERNAL_API_KEY.strip()
    try:
        with _client() as c:
            r = c.post(url, json={"user_id": user_id}, headers=headers)
    except httpx.RequestError as e:
        raise AppException("User service unavailable", status_code=503) from e
    if r.status_code == 401:
        raise AppException("User service unauthorized", status_code=503)
    if r.status_code >= 400:
        raise AppException("User not found", status_code=404)
    try:
        data = r.json()
    except json.JSONDecodeError as e:
        raise AppException("User not found", status_code=404) from e
    if not data.get("valid"):
        raise AppException("User not found", status_code=404)


def fetch_user_profile(user_id: str) -> dict[str, str | None]:
    """Return minimal user profile (full_name, mobile_no) via User MS internal API.

    Returns empty values when integration is disabled or user not found.
    """
    base = settings.USER_MS_BASE_URL.strip()
    if not base:
        return {"user_id": user_id, "full_name": None, "mobile_no": None}
    url = f"{base.rstrip('/')}{settings.USER_MS_INTERNAL_PROFILE_PATH}"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if settings.USER_MS_INTERNAL_API_KEY.strip():
        headers["X-Internal-Api-Key"] = settings.USER_MS_INTERNAL_API_KEY.strip()
    try:
        with _client() as c:
            r = c.post(url, json={"user_id": user_id}, headers=headers)
    except httpx.RequestError:
        return {"user_id": user_id, "full_name": None, "mobile_no": None}
    if r.status_code >= 400:
        return {"user_id": user_id, "full_name": None, "mobile_no": None}
    try:
        data = r.json()
    except json.JSONDecodeError:
        return {"user_id": user_id, "full_name": None, "mobile_no": None}
    return {
        "user_id": str(data.get("user_id") or user_id),
        "full_name": (str(data.get("full_name")) if data.get("full_name") is not None else None),
        "mobile_no": (str(data.get("mobile_no")) if data.get("mobile_no") is not None else None),
    }


def fetch_vehicle_owner(vehicle_id: str) -> str | None:
    """Return owning user_id from Vehicle MS, or None if integration disabled."""
    base = settings.VEHICLE_MS_BASE_URL.strip()
    if not base:
        return None
    url = f"{base.rstrip('/')}{settings.VEHICLE_MS_INTERNAL_DETAILS_PATH}"
    headers: dict[str, str] = {}
    if settings.VEHICLE_MS_INTERNAL_API_KEY.strip():
        headers["X-Internal-Api-Key"] = settings.VEHICLE_MS_INTERNAL_API_KEY.strip()
    try:
        with _client() as c:
            r = c.post(url, json={"vehicle_id": vehicle_id}, headers=headers)
    except httpx.RequestError as e:
        raise AppException("Vehicle service unavailable", status_code=503) from e
    if r.status_code >= 400:
        raise AppException("Vehicle not found", status_code=404)
    try:
        data = r.json()
    except json.JSONDecodeError as e:
        raise AppException("Vehicle not found", status_code=404) from e
    uid = data.get("user_id")
    return str(uid) if uid else None


def assert_vehicle_belongs_to_customer(vehicle_id: str, customer_id: str) -> None:
    owner = fetch_vehicle_owner(vehicle_id)
    if owner is None:
        return
    if owner != customer_id:
        raise AppException("Vehicle does not belong to customer", status_code=400)


def send_notification_event(
    *,
    title: str,
    body: str,
    user_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    base = settings.NOTIFICATION_MS_BASE_URL.strip()
    if not base:
        logger.warning(
            "NOTIFICATION_MS_BASE_URL is empty; skipping notification title=%r user_id=%r",
            title,
            user_id,
        )
        return
    url = f"{base.rstrip('/')}{settings.NOTIFICATION_MS_SEND_PATH}"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if settings.NOTIFICATION_INTERNAL_API_KEY.strip():
        headers["X-Internal-Api-Key"] = settings.NOTIFICATION_INTERNAL_API_KEY.strip()
    payload = {
        "channel": "push",
        "user_id": user_id,
        "title": title,
        "body": body,
        "data": data or {},
        "tokens": [],
    }
    try:
        with _client() as c:
            r = c.post(url, json=payload, headers=headers)
        if r.status_code >= 400:
            logger.warning(
                "Notification MS returned %s for title=%r user_id=%r body=%s",
                r.status_code,
                title,
                user_id,
                (r.text or "")[:500],
            )
    except httpx.RequestError as e:
        logger.warning("Notification MS unreachable for title=%r user_id=%r: %s", title, user_id, e)
        return


def fetch_recovery_user_ids() -> list[str]:
    """Resolve active recovery-field user_ids via User MS internal API."""
    base = settings.USER_MS_BASE_URL.strip()
    path = settings.USER_MS_INTERNAL_LIST_RECOVERY_IDS_PATH.strip()
    if not base or not path:
        return []
    url = f"{base.rstrip('/')}{path}"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if settings.USER_MS_INTERNAL_API_KEY.strip():
        headers["X-Internal-Api-Key"] = settings.USER_MS_INTERNAL_API_KEY.strip()
    try:
        with _client() as c:
            # Only logged-in recovery accounts (agents). Technicians/bays are lookup data without user rows.
            r = c.post(url, json={"role_types": ["agent"]}, headers=headers)
    except httpx.RequestError:
        return []
    if r.status_code >= 400:
        return []
    try:
        data = r.json()
    except json.JSONDecodeError:
        return []
    raw = data.get("user_ids")
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if x]


def notify_recovery_team(*, title: str, body: str, data: dict[str, Any] | None = None) -> None:
    for uid in fetch_recovery_user_ids():
        send_notification_event(title=title, body=body, user_id=uid, data=data)
