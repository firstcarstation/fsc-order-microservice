from __future__ import annotations

import os
import math
import uuid
import mimetypes
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppException
from app.integrations.outbound import (
    assert_vehicle_belongs_to_customer,
    fetch_user_profile,
    notify_recovery_team,
    send_notification_event,
    validate_user_remote,
)
from app.models.order_enums import (
    BayStatusEnum,
    IssueStatusEnum,
    JobStatusEnum,
    JobTypeEnum,
    MessageTypeEnum,
    PaymentStatusEnum,
    PhotoStageEnum,
)
from app.models.order_models import (
    Bay,
    ChatMessage,
    GarageSettings,
    Job,
    JobIssue,
    JobLocationLog,
    JobPhoto,
    JobService,
    Payment,
    Quotation,
    ServiceCatalogue,
    SosIssueType,
    Technician,
)
from app.api.deps import AuthContext
from app.realtime.tracking_hub import tracking_hub


def _s3_enabled() -> bool:
    return bool(
        (settings.AWS_S3_BUCKET or "").strip()
        and (settings.AWS_PUBLIC_BASE_URL or "").strip()
        and (settings.AWS_REGION or "").strip()
        and (settings.AWS_ACCESS_KEY_ID or "").strip()
        and (settings.AWS_SECRET_ACCESS_KEY or "").strip()
    )


def _s3_public_url_for_key(key: str) -> str:
    base = (settings.AWS_PUBLIC_BASE_URL or "").strip().rstrip("/")
    k = key.lstrip("/")
    return f"{base}/{k}"


def _s3_put_bytes(*, key: str, data: bytes, filename: str) -> str:
    # Local import so the service still boots when boto3 isn't installed.
    import boto3  # type: ignore

    content_type, _ = mimetypes.guess_type(filename)
    s3 = boto3.client(
        "s3",
        region_name=settings.AWS_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    )
    s3.put_object(
        Bucket=settings.AWS_S3_BUCKET,
        Key=key,
        Body=data,
        ContentType=content_type or "application/octet-stream",
    )
    return _s3_public_url_for_key(key)

try:  # optional runtime dep
    import stripe  # type: ignore
except Exception:  # pragma: no cover
    stripe = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _touch_job_milestones(job: Job, new_status: JobStatusEnum) -> None:
    """Set first-seen milestone timestamps for customer timeline."""
    now = _now()
    if new_status == JobStatusEnum.VEHICLE_PICKED_UP and job.picked_up_at is None:
        job.picked_up_at = now
    if new_status in (JobStatusEnum.AT_GARAGE, JobStatusEnum.UNDER_INSPECTION) and job.garage_arrived_at is None:
        job.garage_arrived_at = now
    if new_status == JobStatusEnum.DELIVERED and job.delivered_at is None:
        job.delivered_at = now


def _dec(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    return v


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two points (km)."""
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def _eta_minutes_from_distance(distance_km: float) -> int:
    # Simple “free” ETA model: city-average speed + buffer.
    speed_kmh = 28.0
    base = (distance_km / speed_kmh) * 60.0
    mins = int(math.ceil(base + 4.0))
    # Hard cap to keep “fallback ETA” reasonable.
    return max(3, min(mins, 92))


def _job_number_next(db: Session) -> str:
    year = _now().year
    prefix = f"JOB-{year}-"
    n = db.query(func.count(Job.job_id)).filter(Job.job_number.like(f"{prefix}%")).scalar() or 0
    return f"{prefix}{int(n) + 1:05d}"


def _status_str(s: Any) -> str:
    return s.value if hasattr(s, "value") else str(s)


def _chat_last_message_preview(db: Session, job_id: str) -> dict[str, Any] | None:
    m = (
        db.query(ChatMessage)
        .filter(ChatMessage.job_id == job_id)
        .order_by(ChatMessage.created_at.desc())
        .first()
    )
    if m is None:
        return None
    body = (m.body or "").strip()
    mt = _status_str(m.message_type)
    if not body:
        if mt == "issue_list":
            body = "Inspection items"
        elif mt == "quotation":
            body = "Quotation"
        elif mt == "image":
            body = "Photo"
        elif mt == "system":
            body = "Update"
        else:
            body = mt.replace("_", " ").title()
    return {
        "message_type": mt,
        "body": body,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "sender_id": m.sender_id,
    }


def _is_staff(ctx: AuthContext) -> bool:
    """Admin UI + hub managers see all jobs and staff-only actions."""
    return ctx.role_type in ("admin", "hub_manager")


def garage_settings_get_api(db: Session, ctx: AuthContext) -> dict[str, Any]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    row = db.query(GarageSettings).filter(GarageSettings.id == 1).first()
    if row is None:
        row = GarageSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return {
        "address_line_1": row.address_line_1,
        "lat": _dec(row.lat),
        "lng": _dec(row.lng),
        "contact_name": row.contact_name,
        "contact_phone": row.contact_phone,
        "contact_email": row.contact_email,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def garage_settings_update_api(db: Session, ctx: AuthContext, payload: dict[str, Any]) -> dict[str, str]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    row = db.query(GarageSettings).filter(GarageSettings.id == 1).first()
    if row is None:
        row = GarageSettings(id=1)
        db.add(row)
        db.flush()
    if "address_line_1" in payload:
        row.address_line_1 = (str(payload.get("address_line_1") or "").strip() or None)
    if "lat" in payload:
        v = payload.get("lat")
        row.lat = Decimal(str(v)) if v is not None and str(v).strip() != "" else None
    if "lng" in payload:
        v = payload.get("lng")
        row.lng = Decimal(str(v)) if v is not None and str(v).strip() != "" else None
    if "contact_name" in payload:
        row.contact_name = (str(payload.get("contact_name") or "").strip() or None)
    if "contact_phone" in payload:
        row.contact_phone = (str(payload.get("contact_phone") or "").strip() or None)
    if "contact_email" in payload:
        row.contact_email = (str(payload.get("contact_email") or "").strip() or None)
    row.updated_at = _now()
    # Jobs snapshot garage_lat/lng at creation; refresh all non-terminal jobs so recovery sees updates.
    if row.lat is not None and row.lng is not None:
        db.query(Job).filter(Job.status.notin_([JobStatusEnum.DELIVERED, JobStatusEnum.CANCELLED])).update(
            {"garage_lat": row.lat, "garage_lng": row.lng},
            synchronize_session=False,
        )
    db.commit()
    return {"message": "Updated"}


def get_job(db: Session, job_id: str) -> Job | None:
    return db.query(Job).filter(Job.job_id == job_id).first()


def assert_job_view(db: Session, job_id: str, ctx: AuthContext) -> Job:
    job = get_job(db, job_id)
    if job is None:
        raise AppException("Job not found", status_code=404)
    if _is_staff(ctx):
        return job
    if str(job.customer_id) == ctx.user_id:
        return job
    if job.agent_id and str(job.agent_id) == ctx.user_id:
        return job
    # Recovery roles may open unclaimed SOS/service jobs (e.g. map + claim).
    if ctx.role_type in ("agent", "mechanic", "technician"):
        if job.agent_id is None and job.status == JobStatusEnum.PENDING:
            return job
    raise AppException("Forbidden", status_code=403)


def create_sos_job(
    db: Session,
    ctx: AuthContext,
    *,
    customer_id: str,
    vehicle_id: str,
    pickup_lat: float,
    pickup_lng: float,
    pickup_address: str,
    sos_issue_type_ids: list[str],
    customer_note: str | None,
) -> dict[str, Any]:
    if not _is_staff(ctx) and customer_id != ctx.user_id:
        raise AppException("Forbidden", status_code=403)
    validate_user_remote(customer_id)
    assert_vehicle_belongs_to_customer(vehicle_id, customer_id)
    prof = fetch_user_profile(customer_id)
    gs = db.query(GarageSettings).filter(GarageSettings.id == 1).first()
    job = Job(
        job_id=str(uuid.uuid4()),
        job_number=_job_number_next(db),
        job_type=JobTypeEnum.SOS,
        status=JobStatusEnum.PENDING,
        customer_id=customer_id,
        customer_name=prof.get("full_name"),
        customer_mobile_no=prof.get("mobile_no"),
        vehicle_id=vehicle_id,
        pickup_address=pickup_address,
        pickup_lat=Decimal(str(pickup_lat)),
        pickup_lng=Decimal(str(pickup_lng)),
        garage_lat=(gs.lat if gs else None),
        garage_lng=(gs.lng if gs else None),
        sos_issue_type_ids=sos_issue_type_ids or None,
        customer_note=customer_note,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    send_notification_event(
        title="SOS received",
        body=f"Job {job.job_number} created",
        user_id=customer_id,
        data={"job_id": job.job_id},
    )
    notify_recovery_team(
        title="New SOS job",
        body=f"{job.job_number} — open the app to claim.",
        data={"job_id": job.job_id, "job_number": job.job_number, "kind": "sos"},
    )
    return {"job_id": job.job_id, "job_number": job.job_number, "status": _status_str(job.status)}


def create_service_job(
    db: Session,
    ctx: AuthContext,
    *,
    customer_id: str,
    vehicle_id: str,
    service_ids: list[str],
    scheduled_at: datetime | None,
    pickup_lat: float,
    pickup_lng: float,
    pickup_address: str,
    customer_note: str | None,
) -> dict[str, Any]:
    if not _is_staff(ctx) and customer_id != ctx.user_id:
        raise AppException("Forbidden", status_code=403)
    validate_user_remote(customer_id)
    assert_vehicle_belongs_to_customer(vehicle_id, customer_id)
    prof = fetch_user_profile(customer_id)
    gs = db.query(GarageSettings).filter(GarageSettings.id == 1).first()
    # Capacity guard: prevent overbooking the exact slot.
    if scheduled_at is not None:
        cap = int(getattr(settings, "MAX_SERVICE_BOOKINGS_PER_SLOT", 10) or 10)
        if cap > 0:
            n = (
                db.query(Job)
                .filter(
                    Job.job_type == JobTypeEnum.SERVICE,
                    Job.scheduled_at == scheduled_at,
                    Job.status.notin_([JobStatusEnum.CANCELLED, JobStatusEnum.DELIVERED]),
                )
                .count()
            )
            if n >= cap:
                raise AppException("No available slots for this time", status_code=409)
    job = Job(
        job_id=str(uuid.uuid4()),
        job_number=_job_number_next(db),
        job_type=JobTypeEnum.SERVICE,
        status=JobStatusEnum.PENDING,
        customer_id=customer_id,
        customer_name=prof.get("full_name"),
        customer_mobile_no=prof.get("mobile_no"),
        vehicle_id=vehicle_id,
        pickup_address=pickup_address or "Scheduled service",
        pickup_lat=Decimal(str(pickup_lat)),
        pickup_lng=Decimal(str(pickup_lng)),
        garage_lat=(gs.lat if gs else None),
        garage_lng=(gs.lng if gs else None),
        scheduled_at=scheduled_at,
        customer_note=customer_note,
    )
    db.add(job)
    db.flush()
    for sid in service_ids:
        db.add(JobService(id=str(uuid.uuid4()), job_id=job.job_id, service_id=sid))
    # Seed a system message so the booking appears in "Messages" immediately.
    db.add(
        ChatMessage(
            message_id=str(uuid.uuid4()),
            job_id=job.job_id,
            sender_id=customer_id,
            message_type=MessageTypeEnum.SYSTEM,
            body="Service booking created",
            payload={
                "kind": "service_booking",
                "job_id": job.job_id,
                "job_number": job.job_number,
                "customer_id": customer_id,
                "customer_name": prof.get("full_name"),
                "customer_mobile_no": prof.get("mobile_no"),
                "vehicle_id": vehicle_id,
                "service_ids": service_ids,
                "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
                "pickup_address": pickup_address,
            },
            is_read=False,
        )
    )
    db.commit()
    db.refresh(job)
    notify_recovery_team(
        title="New service booking",
        body=f"{job.job_number} — open the app to claim.",
        data={"job_id": job.job_id, "job_number": job.job_number, "kind": "service"},
    )
    send_notification_event(
        title="Service booked",
        body=f"Job {job.job_number} is pending assignment.",
        user_id=customer_id,
        data={"job_id": job.job_id},
    )
    return {"job_id": job.job_id, "job_number": job.job_number, "status": _status_str(job.status)}


def create_admin_ticket_job(
    db: Session,
    ctx: AuthContext,
    *,
    customer_id: str,
    vehicle_id: str,
    service_ids: list[str],
    vehicle_model: str | None,
    plate_number: str | None,
    vin_number: str | None,
    admin_note: str | None,
) -> dict[str, Any]:
    """Admin creates a ticket for an in-workshop vehicle.

    - Does NOT dispatch to recovery team (vehicle is already at garage).
    - Sets status to `at_garage` to match admin workflow screens.
    """
    if not _is_staff(ctx):
        raise AppException("Forbidden", status_code=403)
    validate_user_remote(customer_id)
    assert_vehicle_belongs_to_customer(vehicle_id, customer_id)
    prof = fetch_user_profile(customer_id)
    gs = db.query(GarageSettings).filter(GarageSettings.id == 1).first()

    # Keep required pickup fields non-null, but mark as garage intake.
    pickup_address = "Garage intake"
    job = Job(
        job_id=str(uuid.uuid4()),
        job_number=_job_number_next(db),
        job_type=JobTypeEnum.SERVICE,
        status=JobStatusEnum.AT_GARAGE,
        customer_id=customer_id,
        customer_name=prof.get("full_name"),
        customer_mobile_no=prof.get("mobile_no"),
        vehicle_id=vehicle_id,
        pickup_address=pickup_address,
        pickup_lat=Decimal("0"),
        pickup_lng=Decimal("0"),
        garage_lat=(gs.lat if gs else None),
        garage_lng=(gs.lng if gs else None),
        admin_note=admin_note,
        customer_note=None,
    )
    db.add(job)
    db.flush()
    for sid in service_ids:
        db.add(JobService(id=str(uuid.uuid4()), job_id=job.job_id, service_id=sid))
    _touch_job_milestones(job, JobStatusEnum.AT_GARAGE)
    db.commit()
    db.refresh(job)

    # Inform the customer (in-app notification) that a ticket was opened.
    extra = []
    if plate_number:
        extra.append(str(plate_number))
    if vehicle_model:
        extra.append(str(vehicle_model))
    vehicle_line = f" ({' • '.join(extra)})" if extra else ""
    send_notification_event(
        title="Ticket created",
        body=f"{job.job_number}{vehicle_line} opened by garage.",
        user_id=customer_id,
        data={"job_id": job.job_id},
    )
    return {"job_id": job.job_id, "job_number": job.job_number, "status": _status_str(job.status)}


def list_jobs_api(
    db: Session,
    ctx: AuthContext,
    *,
    customer_id: str | None,
    agent_id: str | None,
    status: str | None,
    page: int,
    limit: int,
) -> dict[str, Any]:
    q = db.query(Job)
    if not _is_staff(ctx):
        if customer_id and customer_id != ctx.user_id:
            raise AppException("Forbidden", status_code=403)
        if agent_id and agent_id != ctx.user_id:
            raise AppException("Forbidden", status_code=403)
        if customer_id:
            q = q.filter(Job.customer_id == customer_id)
        elif agent_id:
            q = q.filter(Job.agent_id == agent_id)
        else:
            if ctx.role_type in ("agent", "mechanic", "technician"):
                q = q.filter(
                    or_(
                        Job.agent_id == ctx.user_id,
                        and_(Job.agent_id.is_(None), Job.status == JobStatusEnum.PENDING),
                    )
                )
            else:
                q = q.filter((Job.customer_id == ctx.user_id) | (Job.agent_id == ctx.user_id))
    else:
        if customer_id:
            q = q.filter(Job.customer_id == customer_id)
        if agent_id:
            q = q.filter(Job.agent_id == agent_id)
    if status:
        try:
            q = q.filter(Job.status == JobStatusEnum(status))
        except ValueError:
            pass
    total = q.count()
    rows = (
        q.order_by(Job.created_at.desc())
        .offset(max(page - 1, 0) * limit)
        .limit(min(limit, 100))
        .all()
    )
    reader_id = ctx.user_id
    agent_cache: dict[str, dict[str, Any]] = {}
    jobs = [
        {
            "job_id": r.job_id,
            "job_number": r.job_number,
            "status": _status_str(r.status),
            "job_type": _status_str(r.job_type),
            "customer_id": r.customer_id,
            "customer_name": getattr(r, "customer_name", None),
            "customer_mobile_no": getattr(r, "customer_mobile_no", None),
            "agent_id": r.agent_id,
            "agent_name": (
                (agent_cache.setdefault(str(r.agent_id), fetch_user_profile(str(r.agent_id))) or {}).get("full_name")
                if (_is_staff(ctx) and r.agent_id)
                else None
            ),
            "vehicle_id": r.vehicle_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "scheduled_at": r.scheduled_at.isoformat() if r.scheduled_at else None,
            "eta_minutes": getattr(r, "eta_minutes", None),
            "eta_distance_km": _dec(getattr(r, "eta_distance_km", None)),
            "eta_updated_at": r.eta_updated_at.isoformat() if getattr(r, "eta_updated_at", None) else None,
            "pickup_address": r.pickup_address,
            "sos_issue_type_ids": getattr(r, "sos_issue_type_ids", None),
            "customer_note": getattr(r, "customer_note", None),
            "garage_lat": _dec(getattr(r, "garage_lat", None)),
            "garage_lng": _dec(getattr(r, "garage_lng", None)),
            "last_message": _chat_last_message_preview(db, r.job_id),
            "unread_count": int(
                db.query(ChatMessage)
                .filter(ChatMessage.job_id == r.job_id, ChatMessage.is_read.is_(False), ChatMessage.sender_id != reader_id)
                .count()
            )
            if reader_id
            else 0,
        }
        for r in rows
    ]
    return {"jobs": jobs, "total": total}


def job_to_full_dict(db: Session, job: Job, *, hide_customer_note: bool = False) -> dict[str, Any]:
    services = [
        {"service_id": js.service_id, "id": js.id}
        for js in db.query(JobService).filter(JobService.job_id == job.job_id).all()
    ]
    issues = [
        {
            "issue_id": i.issue_id,
            "title": i.title,
            "description": i.description,
            "photo_url": i.photo_url,
            "estimated_cost": _dec(i.estimated_cost),
            "status": _status_str(i.status),
            "sort_order": i.sort_order,
        }
        for i in db.query(JobIssue).filter(JobIssue.job_id == job.job_id).order_by(JobIssue.sort_order).all()
    ]
    photos = [
        {
            "photo_id": p.photo_id,
            "stage": _status_str(p.stage),
            "photo_url": p.photo_url,
            "caption": p.caption,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in db.query(JobPhoto).filter(JobPhoto.job_id == job.job_id).all()
    ]
    qrow = db.query(Quotation).filter(Quotation.job_id == job.job_id).first()
    quotation = None
    if qrow:
        quotation = {
            "quotation_id": qrow.quotation_id,
            "issues_total": _dec(qrow.issues_total),
            "labour_charge": _dec(qrow.labour_charge),
            "discount": _dec(qrow.discount),
            "total_amount": _dec(qrow.total_amount),
            "advance_required": _dec(qrow.advance_required),
            "balance_due": _dec(qrow.balance_due),
            "customer_accepted": qrow.customer_accepted,
        }
    return {
        "job_id": job.job_id,
        "job_number": job.job_number,
        "status": _status_str(job.status),
        "job_type": _status_str(job.job_type),
        "customer_id": job.customer_id,
        "customer_name": getattr(job, "customer_name", None),
        "customer_mobile_no": getattr(job, "customer_mobile_no", None),
        "agent_id": job.agent_id,
        "vehicle_id": job.vehicle_id,
        "bay_id": job.bay_id,
        "technician_id": getattr(job, "technician_id", None),
        "pickup_address": job.pickup_address,
        "pickup_lat": _dec(job.pickup_lat),
        "pickup_lng": _dec(job.pickup_lng),
        "garage_lat": _dec(getattr(job, "garage_lat", None)),
        "garage_lng": _dec(getattr(job, "garage_lng", None)),
        "sos_issue_type_ids": job.sos_issue_type_ids,
        "customer_note": None if hide_customer_note else job.customer_note,
        "admin_note": job.admin_note,
        "payment_status": _status_str(job.payment_status),
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
        "eta_minutes": getattr(job, "eta_minutes", None),
        "eta_distance_km": _dec(getattr(job, "eta_distance_km", None)),
        "eta_updated_at": job.eta_updated_at.isoformat() if getattr(job, "eta_updated_at", None) else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "picked_up_at": job.picked_up_at.isoformat() if job.picked_up_at else None,
        "garage_arrived_at": job.garage_arrived_at.isoformat() if job.garage_arrived_at else None,
        "delivered_at": job.delivered_at.isoformat() if job.delivered_at else None,
        "delivery_address": getattr(job, "delivery_address", None),
        "delivery_lat": _dec(getattr(job, "delivery_lat", None)),
        "delivery_lng": _dec(getattr(job, "delivery_lng", None)),
        "services": services,
        "issues": issues,
        "photos": photos,
        "quotation": quotation,
    }


def set_delivery_location_api(
    db: Session,
    ctx: AuthContext,
    *,
    job_id: str,
    delivery_address: str,
    delivery_lat: float | None,
    delivery_lng: float | None,
) -> dict[str, Any]:
    job = assert_job_view(db, job_id, ctx)
    if str(job.customer_id) != ctx.user_id:
        raise AppException("Customer only", status_code=403)
    job.delivery_address = delivery_address.strip() or None
    job.delivery_lat = Decimal(str(delivery_lat)) if delivery_lat is not None else None
    job.delivery_lng = Decimal(str(delivery_lng)) if delivery_lng is not None else None
    job.updated_at = _now()
    db.add(
        ChatMessage(
            message_id=str(uuid.uuid4()),
            job_id=job.job_id,
            sender_id=ctx.user_id,
            message_type=MessageTypeEnum.SYSTEM,
            body="Delivery location provided",
            payload={
                "kind": "delivery_location",
                "delivery_address": job.delivery_address,
                "delivery_lat": _dec(job.delivery_lat),
                "delivery_lng": _dec(job.delivery_lng),
            },
        )
    )
    db.commit()
    return {"job_id": job.job_id, "delivery_address": job.delivery_address}


def technicians_list_api(db: Session, ctx: AuthContext) -> list[dict[str, Any]]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    rows = db.query(Technician).order_by(Technician.sort_order, Technician.name).all()
    return [
        {
            "technician_id": r.technician_id,
            "name": r.name,
            "is_active": bool(r.is_active),
            "sort_order": r.sort_order,
        }
        for r in rows
    ]


def technician_create_api(db: Session, ctx: AuthContext, *, name: str, sort_order: int = 0) -> dict[str, Any]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    if not name.strip():
        raise AppException("Invalid name", status_code=400)
    row = Technician(technician_id=str(uuid.uuid4()), name=name.strip(), sort_order=int(sort_order or 0), is_active=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"technician_id": row.technician_id}


def technician_update_api(db: Session, ctx: AuthContext, technician_id: str, data: dict[str, Any]) -> dict[str, Any]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    row = db.query(Technician).filter(Technician.technician_id == technician_id).first()
    if row is None:
        raise AppException("Not found", status_code=404)
    if "name" in data and data["name"] is not None:
        nm = str(data["name"]).strip()
        if not nm:
            raise AppException("Invalid name", status_code=400)
        row.name = nm
    if "sort_order" in data:
        row.sort_order = int(data["sort_order"] or 0)
    db.commit()
    return {"technician_id": row.technician_id}


def technician_toggle_api(db: Session, ctx: AuthContext, *, technician_id: str, is_active: bool) -> dict[str, str]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    row = db.query(Technician).filter(Technician.technician_id == technician_id).first()
    if row is None:
        raise AppException("Not found", status_code=404)
    row.is_active = bool(is_active)
    db.commit()
    return {"message": "ok"}


def technician_delete_api(db: Session, ctx: AuthContext, technician_id: str) -> dict[str, str]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    row = db.query(Technician).filter(Technician.technician_id == technician_id).first()
    if row:
        db.delete(row)
        db.commit()
    return {"message": "ok"}


def assign_technician_api(db: Session, ctx: AuthContext, *, job_id: str, technician_id: str | None) -> dict[str, str]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    job = get_job(db, job_id)
    if job is None:
        raise AppException("Job not found", status_code=404)
    if technician_id:
        tech = db.query(Technician).filter(Technician.technician_id == technician_id).first()
        if tech is None:
            raise AppException("Technician not found", status_code=404)
        if not tech.is_active:
            raise AppException("Technician inactive", status_code=400)
    setattr(job, "technician_id", technician_id)
    job.updated_at = _now()
    db.commit()
    return {"message": "Technician assigned"}


def job_details_api(db: Session, ctx: AuthContext, job_id: str) -> dict[str, Any]:
    job = assert_job_view(db, job_id, ctx)
    # Customer note ("special instructions") should be visible to all roles including recovery.
    payload = job_to_full_dict(db, job, hide_customer_note=False)
    if _is_staff(ctx) and payload.get("agent_id"):
        try:
            prof = fetch_user_profile(str(payload["agent_id"]))
            payload["agent_name"] = (prof or {}).get("full_name")
        except Exception:
            pass
    return payload


def update_job_status_api(
    db: Session,
    ctx: AuthContext,
    *,
    job_id: str,
    status: str,
    note: str | None,
    agent_lat: float | None = None,
    agent_lng: float | None = None,
) -> dict[str, Any]:
    job = assert_job_view(db, job_id, ctx)
    try:
        new_st = JobStatusEnum(status)
    except ValueError as e:
        raise AppException("Invalid status", status_code=400) from e
    prev = _status_str(job.status)
    job.status = new_st
    _touch_job_milestones(job, new_st)
    if note:
        job.admin_note = (job.admin_note or "") + ("\n" if job.admin_note else "") + note
    # Transparency: log recovery/admin updates into chat for the customer.
    db.add(
        ChatMessage(
            message_id=str(uuid.uuid4()),
            job_id=job.job_id,
            sender_id=ctx.user_id,
            message_type=MessageTypeEnum.SYSTEM,
            body=None,
            payload={
                "kind": "status_update",
                "from": prev,
                "to": _status_str(new_st),
                "note": note,
                "by_role": ctx.role_type,
            },
        )
    )
    job.updated_at = _now()
    db.commit()
    # Best-effort customer ETA updates:
    # - agent_en_route: reuse existing ETA (agent -> pickup)
    # - in_transit_to_garage: compute pickup -> garage ETA (free heuristic)
    try:
        if new_st == JobStatusEnum.AGENT_EN_ROUTE:
            # If agent shares current location, recompute ETA to pickup for clarity.
            if agent_lat is not None and agent_lng is not None:
                p_lat = float(job.pickup_lat or 0)
                p_lng = float(job.pickup_lng or 0)
                if p_lat != 0 and p_lng != 0:
                    dist = _haversine_km(float(agent_lat), float(agent_lng), p_lat, p_lng)
                    job.eta_distance_km = Decimal(f"{dist:.2f}")
                    job.eta_minutes = _eta_minutes_from_distance(dist)
                    job.eta_updated_at = _now()
                    job.updated_at = _now()
                    db.commit()
            if getattr(job, "eta_minutes", None) is not None:
                eta = int(job.eta_minutes)
                # Chat for transparency (admin + customer can see instantly).
                db.add(
                    ChatMessage(
                        message_id=str(uuid.uuid4()),
                        job_id=job.job_id,
                        sender_id=ctx.user_id,
                        message_type=MessageTypeEnum.SYSTEM,
                        body=None,
                        payload={"kind": "eta_update", "to": "pickup", "eta_minutes": eta},
                    )
                )
                db.commit()
            send_notification_event(
                title="Recovery on the way",
                body=f"Estimated arrival in {eta} min.",
                user_id=str(job.customer_id),
                data={"job_id": job.job_id},
            )
        if new_st == JobStatusEnum.READY_FOR_DELIVERY:
            # Ask customer for delivery location (chat + push). Best-effort.
            db.add(
                ChatMessage(
                    message_id=str(uuid.uuid4()),
                    job_id=job.job_id,
                    sender_id=ctx.user_id,
                    message_type=MessageTypeEnum.SYSTEM,
                    body=None,
                    payload={"kind": "request_delivery_location"},
                )
            )
            db.commit()
            send_notification_event(
                title="Delivery location needed",
                body="Please share where you want the car delivered.",
                user_id=str(job.customer_id),
                data={"job_id": job.job_id, "kind": "request_delivery_location"},
            )
        if new_st == JobStatusEnum.IN_TRANSIT_TO_GARAGE:
            p_lat = float(job.pickup_lat or 0)
            p_lng = float(job.pickup_lng or 0)
            g_lat = float(getattr(job, "garage_lat", 0) or 0)
            g_lng = float(getattr(job, "garage_lng", 0) or 0)
            if p_lat != 0 and p_lng != 0 and g_lat != 0 and g_lng != 0:
                dist = _haversine_km(p_lat, p_lng, g_lat, g_lng)
                eta = _eta_minutes_from_distance(dist)
                job.eta_distance_km = Decimal(f"{dist:.2f}")
                job.eta_minutes = eta
                job.eta_updated_at = _now()
                job.updated_at = _now()
                db.commit()
                db.add(
                    ChatMessage(
                        message_id=str(uuid.uuid4()),
                        job_id=job.job_id,
                        sender_id=ctx.user_id,
                        message_type=MessageTypeEnum.SYSTEM,
                        body=None,
                        payload={"kind": "eta_update", "to": "garage", "eta_minutes": int(eta)},
                    )
                )
                db.commit()
                send_notification_event(
                    title="Heading to garage",
                    body=f"Estimated arrival in {int(eta)} min.",
                    user_id=str(job.customer_id),
                    data={"job_id": job.job_id},
                )
    except Exception:
        pass
    return {"job_id": job.job_id, "status": _status_str(job.status), "updated_at": job.updated_at.isoformat()}


def assign_agent_api(db: Session, ctx: AuthContext, *, job_id: str, agent_id: str) -> dict[str, str]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    validate_user_remote(agent_id)
    job = get_job(db, job_id)
    if job is None:
        raise AppException("Job not found", status_code=404)
    job.agent_id = agent_id
    job.status = JobStatusEnum.ASSIGNED
    job.updated_at = _now()
    db.commit()
    send_notification_event(
        title="Job assigned",
        body=f"You were assigned {job.job_number}",
        user_id=agent_id,
        data={"job_id": job.job_id},
    )
    return {"message": "Agent assigned"}


def schedule_delivery_api(
    db: Session,
    ctx: AuthContext,
    *,
    job_id: str,
    driver_id: str,
    scheduled_at: datetime,
    note: str | None,
) -> dict[str, Any]:
    """Admin schedules delivery: assigns driver and moves job to OUT_FOR_DELIVERY."""
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    validate_user_remote(driver_id)
    job = get_job(db, job_id)
    if job is None:
        raise AppException("Job not found", status_code=404)
    # Driver availability: reject scheduling if driver already has a nearby assignment.
    window_min = int(getattr(settings, "DRIVER_BUSY_WINDOW_MIN", 60) or 60)
    if window_min > 0:
        start = scheduled_at - timedelta(minutes=window_min)
        end = scheduled_at + timedelta(minutes=window_min)
        conflict = (
            db.query(Job)
            .filter(
                Job.agent_id == driver_id,
                Job.scheduled_at.is_not(None),
                Job.scheduled_at >= start,
                Job.scheduled_at <= end,
                Job.status.notin_([JobStatusEnum.CANCELLED, JobStatusEnum.DELIVERED]),
                Job.job_id != job_id,
            )
            .first()
        )
        if conflict is not None:
            raise AppException("Driver not available at that time", status_code=409)
    job.agent_id = driver_id
    job.scheduled_at = scheduled_at
    # Driver must explicitly start delivery in the app (customer + transparency).
    job.status = JobStatusEnum.DELIVERY_SCHEDULED
    if note:
        job.admin_note = (job.admin_note or "") + ("\n" if job.admin_note else "") + note
    job.updated_at = _now()
    db.add(
        ChatMessage(
            message_id=str(uuid.uuid4()),
            job_id=job.job_id,
            sender_id=ctx.user_id,
            message_type=MessageTypeEnum.SYSTEM,
            body=None,
            payload={
                "kind": "delivery_scheduled",
                "driver_id": driver_id,
                "scheduled_at": scheduled_at.isoformat(),
                "delivery_address": getattr(job, "delivery_address", None),
            },
        )
    )
    db.commit()
    send_notification_event(
        title="Delivery scheduled",
        body=f"{job.job_number} scheduled for delivery.",
        user_id=str(job.customer_id),
        data={"job_id": job.job_id, "kind": "delivery_scheduled"},
    )
    send_notification_event(
        title="Delivery assigned",
        body=f"You were assigned delivery for {job.job_number}",
        user_id=driver_id,
        data={"job_id": job.job_id, "kind": "delivery_assigned"},
    )
    return {"job_id": job.job_id, "status": _status_str(job.status), "scheduled_at": job.scheduled_at.isoformat()}


def start_delivery_api(db: Session, ctx: AuthContext, *, job_id: str) -> dict[str, Any]:
    """Recovery agent taps 'Start delivery' to notify customer.

    This is intentionally separate from status updates because:
    - Scheduling assigns a driver + time.
    - Starting delivery is the real-world "driver is leaving now" moment.
    """
    job = assert_job_view(db, job_id, ctx)
    if not _is_staff(ctx):
        if not job.agent_id or str(job.agent_id) != ctx.user_id:
            raise AppException("Forbidden", status_code=403)
    prev = _status_str(job.status)
    if job.status == JobStatusEnum.DELIVERY_SCHEDULED:
        job.status = JobStatusEnum.OUT_FOR_DELIVERY
        job.updated_at = _now()
    elif job.status == JobStatusEnum.OUT_FOR_DELIVERY:
        # Idempotent: already en route (e.g. double tap).
        return {"job_id": job.job_id, "status": _status_str(job.status), "message": "ok"}
    else:
        raise AppException(
            "Start delivery is only available after admin schedules delivery (delivery_scheduled).",
            status_code=400,
        )
    # Post a system message so it appears in chat instantly for transparency.
    db.add(
        ChatMessage(
            message_id=str(uuid.uuid4()),
            job_id=job.job_id,
            sender_id=ctx.user_id,
            message_type=MessageTypeEnum.SYSTEM,
            body="Delivery started",
            payload={"kind": "delivery_started", "from": prev, "to": _status_str(job.status)},
        )
    )
    db.commit()
    # Push the customer so their app refreshes even if they are on another screen.
    try:
        send_notification_event(
            title="Delivery started",
            body="Your car is on the way to your delivery location.",
            user_id=str(job.customer_id),
            data={"job_id": job.job_id, "kind": "delivery_started"},
        )
    except Exception:
        pass
    return {"job_id": job.job_id, "status": _status_str(job.status), "message": "ok"}


def claim_job_api(
    db: Session,
    ctx: AuthContext,
    *,
    job_id: str,
    agent_lat: float | None,
    agent_lng: float | None,
) -> dict[str, Any]:
    """First recovery agent to claim a pending unassigned job (Uber-style self-assign)."""
    if ctx.role_type not in ("agent", "mechanic", "technician"):
        raise AppException("Recovery agents only", status_code=403)
    # Row lock so two agents claiming the same job cannot both succeed.
    job = db.query(Job).filter(Job.job_id == job_id).with_for_update().first()
    if job is None:
        raise AppException("Job not found", status_code=404)
    if job.agent_id is not None and str(job.agent_id) != ctx.user_id:
        raise AppException("Already assigned to another agent", status_code=409)
    if job.status != JobStatusEnum.PENDING:
        raise AppException("Job is not available to claim", status_code=400)
    job.agent_id = ctx.user_id
    job.status = JobStatusEnum.ASSIGNED
    try:
        if agent_lat is not None and agent_lng is not None:
            p_lat = float(job.pickup_lat or 0)
            p_lng = float(job.pickup_lng or 0)
            if p_lat != 0 and p_lng != 0:
                dist = _haversine_km(float(agent_lat), float(agent_lng), p_lat, p_lng)
                job.eta_distance_km = Decimal(f"{dist:.2f}")
                job.eta_minutes = _eta_minutes_from_distance(dist)
                job.eta_updated_at = _now()
    except Exception:
        # ETA is best-effort; never block claim.
        pass
    if getattr(job, "eta_minutes", None) is None:
        job.eta_minutes = 92
        job.eta_updated_at = _now()
    job.updated_at = _now()
    db.commit()
    # Notify customer with initial ETA (best-effort).
    try:
        if getattr(job, "eta_minutes", None) is not None:
            send_notification_event(
                title="Recovery on the way",
                body=f"Estimated arrival in {int(job.eta_minutes)} min.",
                user_id=str(job.customer_id),
                data={"job_id": job.job_id},
            )
    except Exception:
        pass
    send_notification_event(
        title="Job claimed",
        body=f"You claimed {job.job_number}",
        user_id=ctx.user_id,
        data={"job_id": job.job_id},
    )
    return {
        "job_id": job.job_id,
        "job_number": job.job_number,
        "status": _status_str(job.status),
        "message": "Claimed",
        "eta_minutes": getattr(job, "eta_minutes", None),
        "eta_distance_km": _dec(getattr(job, "eta_distance_km", None)),
        "eta_updated_at": job.eta_updated_at.isoformat() if getattr(job, "eta_updated_at", None) else None,
    }


def assign_bay_api(db: Session, ctx: AuthContext, *, job_id: str, bay_id: str) -> dict[str, str]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    job = get_job(db, job_id)
    if job is None:
        raise AppException("Job not found", status_code=404)
    bay = db.query(Bay).filter(Bay.bay_id == bay_id).first()
    if bay is None:
        raise AppException("Bay not found", status_code=404)
    job.bay_id = bay_id
    bay.status = BayStatusEnum.OCCUPIED
    job.updated_at = _now()
    db.commit()
    return {"message": "Bay assigned"}


def cancel_job_api(db: Session, ctx: AuthContext, *, job_id: str, reason: str) -> dict[str, str]:
    job = assert_job_view(db, job_id, ctx)
    if not _is_staff(ctx) and str(job.customer_id) != ctx.user_id:
        raise AppException("Forbidden", status_code=403)
    job.status = JobStatusEnum.CANCELLED
    job.admin_note = (job.admin_note or "") + f"\nCancelled: {reason}"
    job.updated_at = _now()
    db.commit()
    return {"message": "Cancelled"}


def save_job_photo(
    db: Session,
    ctx: AuthContext,
    *,
    job_id: str,
    stage: str,
    file_bytes: bytes,
    filename: str,
    caption: str | None,
) -> dict[str, Any]:
    job = assert_job_view(db, job_id, ctx)
    try:
        st = PhotoStageEnum(stage)
    except ValueError as e:
        raise AppException("Invalid stage", status_code=400) from e
    max_b = settings.UPLOAD_MAX_MB * 1024 * 1024
    if len(file_bytes) > max_b:
        raise AppException("File too large", status_code=400)
    safe = f"{uuid.uuid4().hex}_{os.path.basename(filename) or 'photo'}"
    rel: str
    if _s3_enabled():
        prefix = (settings.AWS_UPLOAD_PREFIX or "").strip()
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        key = f"{prefix}jobs/{safe}"
        rel = _s3_put_bytes(key=key, data=file_bytes, filename=filename)
    else:
        root = os.path.abspath(settings.LOCAL_UPLOAD_DIR)
        os.makedirs(os.path.join(root, "jobs"), exist_ok=True)
        path = os.path.join(root, "jobs", safe)
        with open(path, "wb") as f:
            f.write(file_bytes)
        rel = f"{settings.PUBLIC_APP_URL.rstrip('/')}/uploads/jobs/{safe}"
    photo = JobPhoto(
        photo_id=str(uuid.uuid4()),
        job_id=job_id,
        stage=st,
        photo_url=rel,
        uploaded_by=ctx.user_id,
        caption=caption,
    )
    db.add(photo)
    # Transparency: post uploaded photo into chat.
    db.add(
        ChatMessage(
            message_id=str(uuid.uuid4()),
            job_id=job_id,
            sender_id=ctx.user_id,
            message_type=MessageTypeEnum.PHOTO,
            body=caption or "Photo uploaded",
            payload={
                "kind": "job_photo",
                "stage": stage,
                "photo_url": rel,
                "caption": caption,
            },
        )
    )
    db.commit()
    return {"photo_id": photo.photo_id, "photo_url": rel, "stage": stage}


def list_job_photos_api(
    db: Session, ctx: AuthContext, job_id: str, stage: str | None
) -> dict[str, list]:
    job = assert_job_view(db, job_id, ctx)
    q = db.query(JobPhoto).filter(JobPhoto.job_id == job_id)
    if stage:
        try:
            q = q.filter(JobPhoto.stage == PhotoStageEnum(stage))
        except ValueError:
            pass
    rows = q.all()
    by_stage: dict[str, list] = {}
    for p in rows:
        k = _status_str(p.stage)
        by_stage.setdefault(k, []).append(
            {"photo_id": p.photo_id, "photo_url": p.photo_url, "caption": p.caption}
        )
    return {"photos": [{"stage": k, "items": v} for k, v in by_stage.items()]}


def catalogue_list_public(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.query(ServiceCatalogue)
        .filter(ServiceCatalogue.is_active.is_(True))
        .order_by(ServiceCatalogue.sort_order)
        .all()
    )
    return [
        {
            "service_id": r.service_id,
            "name": r.name,
            "description": r.description,
            "category": r.category,
            "base_price": _dec(r.base_price),
            "sort_order": r.sort_order,
        }
        for r in rows
    ]


def catalogue_list_admin(db: Session, ctx: AuthContext) -> list[dict[str, Any]]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    rows = db.query(ServiceCatalogue).order_by(ServiceCatalogue.sort_order).all()
    return [
        {
            "service_id": r.service_id,
            "name": r.name,
            "description": r.description,
            "category": r.category,
            "base_price": _dec(r.base_price),
            "sort_order": r.sort_order,
            "is_active": bool(r.is_active),
        }
        for r in rows
    ]


def sos_issues_list_public(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.query(SosIssueType)
        .filter(SosIssueType.is_active.is_(True))
        .order_by(SosIssueType.sort_order)
        .all()
    )
    return [
        {
            "issue_type_id": r.issue_type_id,
            "name": r.name,
            "icon_url": r.icon_url,
            "sort_order": r.sort_order,
        }
        for r in rows
    ]


def tracking_update_api(
    db: Session,
    ctx: AuthContext,
    *,
    job_id: str,
    agent_id: str,
    lat: float,
    lng: float,
    heading: float | None,
    speed_kmh: float | None,
    agent_name: str = "",
) -> dict[str, str]:
    job = get_job(db, job_id)
    if job is None:
        raise AppException("Job not found", status_code=404)
    if not _is_staff(ctx):
        if ctx.user_id != agent_id:
            raise AppException("Forbidden", status_code=403)
        if job.agent_id and str(job.agent_id) != agent_id:
            raise AppException("Forbidden", status_code=403)
    cap = _now()
    log = JobLocationLog(
        log_id=str(uuid.uuid4()),
        job_id=job_id,
        agent_id=agent_id,
        lat=Decimal(str(lat)),
        lng=Decimal(str(lng)),
        heading=Decimal(str(heading)) if heading is not None else None,
        speed_kmh=Decimal(str(speed_kmh)) if speed_kmh is not None else None,
        captured_at=cap,
    )
    db.add(log)
    db.commit()
    payload = {
        "lat": lat,
        "lng": lng,
        "heading": heading,
        "speed_kmh": speed_kmh,
        "agent_name": agent_name,
        "job_status": _status_str(job.status),
        "timestamp": cap.isoformat(),
    }
    tracking_hub.set_redis_latest(job_id, payload)
    return {"message": "ok"}


def tracking_latest_api(db: Session, ctx: AuthContext, job_id: str) -> dict[str, Any]:
    assert_job_view(db, job_id, ctx)
    snap = tracking_hub.get_redis_latest(job_id)
    if snap:
        return snap
    row = (
        db.query(JobLocationLog)
        .filter(JobLocationLog.job_id == job_id)
        .order_by(JobLocationLog.captured_at.desc())
        .first()
    )
    if row is None:
        return {}
    return {
        "lat": _dec(row.lat),
        "lng": _dec(row.lng),
        "heading": _dec(row.heading),
        "speed_kmh": _dec(row.speed_kmh),
        "captured_at": row.captured_at.isoformat(),
    }


def chat_send_api(
    db: Session,
    ctx: AuthContext,
    *,
    job_id: str,
    sender_id: str,
    message_type: str,
    body: str | None,
    payload: dict | None,
) -> dict[str, Any]:
    job = assert_job_view(db, job_id, ctx)
    if sender_id != ctx.user_id and not _is_staff(ctx):
        raise AppException("Forbidden", status_code=403)
    try:
        mt = MessageTypeEnum(message_type)
    except ValueError as e:
        raise AppException("Invalid message_type", status_code=400) from e
    msg = ChatMessage(
        message_id=str(uuid.uuid4()),
        job_id=job_id,
        sender_id=sender_id,
        message_type=mt,
        body=body,
        payload=payload,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    # Push-triggered refresh: notify the other party so their inbox/chat refreshes immediately.
    # Best-effort: chat must succeed even if notifications fail.
    try:
        recipients: set[str] = set()
        # If someone on staff/recovery messages, ping customer.
        if getattr(job, "customer_id", None) and str(job.customer_id) != sender_id:
            recipients.add(str(job.customer_id))
        # If customer messages, ping assigned recovery agent (if any).
        if getattr(job, "agent_id", None) and str(job.agent_id) != sender_id:
            recipients.add(str(job.agent_id))
        for uid in recipients:
            send_notification_event(
                title="New message",
                body="You have a new update in your job chat.",
                user_id=uid,
                data={"job_id": job_id, "kind": "chat_message"},
            )
    except Exception:
        pass

    return {
        "message_id": msg.message_id,
        "job_id": job_id,
        "message_type": message_type,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


def chat_history_api(
    db: Session, ctx: AuthContext, *, job_id: str, page: int, limit: int
) -> dict[str, Any]:
    assert_job_view(db, job_id, ctx)
    q = db.query(ChatMessage).filter(ChatMessage.job_id == job_id)
    total = q.count()
    rows = (
        q.order_by(ChatMessage.created_at.desc())
        .offset(max(page - 1, 0) * limit)
        .limit(min(limit, 200))
        .all()
    )
    messages = [
        {
            "message_id": m.message_id,
            "sender_id": m.sender_id,
            "message_type": _status_str(m.message_type),
            "body": m.body,
            "payload": m.payload,
            "is_read": m.is_read,
            "created_at": m.created_at.isoformat(),
        }
        for m in reversed(rows)
    ]
    return {"messages": messages, "total": total}


def chat_mark_read_api(db: Session, ctx: AuthContext, *, job_id: str, reader_id: str) -> dict[str, int]:
    assert_job_view(db, job_id, ctx)
    if reader_id != ctx.user_id:
        raise AppException("Forbidden", status_code=403)
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.job_id == job_id, ChatMessage.is_read.is_(False), ChatMessage.sender_id != reader_id)
        .all()
    )
    n = 0
    for m in rows:
        m.is_read = True
        m.read_at = _now()
        n += 1
    db.commit()
    return {"updated_count": n}


def send_issue_list_api(
    db: Session,
    ctx: AuthContext,
    *,
    job_id: str,
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    job = get_job(db, job_id)
    if job is None:
        raise AppException("Job not found", status_code=404)
    if job.status not in (JobStatusEnum.AT_GARAGE, JobStatusEnum.UNDER_INSPECTION):
        raise AppException(
            "Issues can only be sent after the vehicle is at the garage (status at_garage or under_inspection)",
            status_code=400,
        )
    created = []
    for i, item in enumerate(issues):
        est_raw = item.get("estimated_cost")
        iss = JobIssue(
            issue_id=str(uuid.uuid4()),
            job_id=job_id,
            title=item["title"],
            description=item.get("description"),
            photo_url=item.get("photo_url"),
            estimated_cost=Decimal(str(est_raw)) if est_raw is not None and str(est_raw).strip() != "" else None,
            sort_order=i,
        )
        db.add(iss)
        created.append(iss.issue_id)
    msg = ChatMessage(
        message_id=str(uuid.uuid4()),
        job_id=job_id,
        sender_id=ctx.user_id,
        message_type=MessageTypeEnum.ISSUE_LIST,
        body=None,
        payload={"issue_ids": created},
    )
    db.add(msg)
    job.status = JobStatusEnum.AWAITING_APPROVAL
    db.commit()
    send_notification_event(
        title="Issues need your review",
        body=f"Job {job.job_number}: please approve or reject each item.",
        user_id=str(job.customer_id),
        data={"job_id": job.job_id},
    )
    return {"issue_ids": created, "message_id": msg.message_id}


def send_quotation_api(
    db: Session,
    ctx: AuthContext,
    *,
    job_id: str,
    labour_charge: float,
    discount: float | None,
    advance_required: float | None,
) -> dict[str, Any]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    job = get_job(db, job_id)
    if job is None:
        raise AppException("Job not found", status_code=404)
    approved = (
        db.query(JobIssue)
        .filter(JobIssue.job_id == job_id, JobIssue.status == IssueStatusEnum.APPROVED)
        .all()
    )
    issues_total = sum((i.estimated_cost or Decimal(0)) for i in approved)
    disc = Decimal(str(discount or 0))
    labour = Decimal(str(labour_charge))
    total = issues_total + labour - disc
    adv = Decimal(str(advance_required or 0))
    if adv < 0:
        adv = Decimal(0)
    if adv > total:
        adv = total
    balance = total - adv
    q = Quotation(
        quotation_id=str(uuid.uuid4()),
        job_id=job_id,
        issues_total=issues_total,
        labour_charge=labour,
        discount=disc,
        total_amount=total,
        advance_required=adv,
        balance_due=balance,
    )
    db.add(q)
    msg = ChatMessage(
        message_id=str(uuid.uuid4()),
        job_id=job_id,
        sender_id=ctx.user_id,
        message_type=MessageTypeEnum.QUOTATION,
        body=None,
        payload={
            "quotation_id": q.quotation_id,
            "total_amount": float(total),
            "advance_required": float(adv),
            "balance_due": float(balance),
        },
    )
    db.add(msg)
    db.commit()
    send_notification_event(
        title="Quotation ready",
        body=f"Job {job.job_number}: review your quote in the app.",
        user_id=str(job.customer_id),
        data={"job_id": job.job_id},
    )
    return {"quotation_id": q.quotation_id, "message_id": msg.message_id}


def issues_respond_api(
    db: Session,
    ctx: AuthContext,
    *,
    job_id: str,
    responses: list[dict[str, str]],
) -> dict[str, Any]:
    job = assert_job_view(db, job_id, ctx)
    if str(job.customer_id) != ctx.user_id:
        raise AppException("Customer only", status_code=403)
    updated = []
    for r in responses:
        iss = db.query(JobIssue).filter(JobIssue.issue_id == r["issue_id"], JobIssue.job_id == job_id).first()
        if iss is None:
            continue
        st = r.get("status", "")
        if st == "approved":
            iss.status = IssueStatusEnum.APPROVED
        elif st == "rejected":
            iss.status = IssueStatusEnum.REJECTED
        iss.responded_at = _now()
        updated.append({"issue_id": iss.issue_id, "status": _status_str(iss.status)})
    # If everything has a response, mark the job as approved (admin can proceed to quotation).
    remaining_pending = (
        db.query(JobIssue)
        .filter(JobIssue.job_id == job_id, JobIssue.status == IssueStatusEnum.PENDING)
        .count()
    )
    if remaining_pending == 0:
        job.status = JobStatusEnum.APPROVED

    # Write a customer-response message so admin can track approvals in Messages view too.
    if updated and remaining_pending == 0:
        db.add(
            ChatMessage(
                message_id=str(uuid.uuid4()),
                job_id=job_id,
                sender_id=ctx.user_id,
                message_type=MessageTypeEnum.SYSTEM,
                body=None,
                payload={"kind": "issue_responses", "responses": updated},
                is_read=False,
            )
        )

    db.commit()
    return {"updated_count": len(updated), "issues": updated}


def issues_list_api(db: Session, ctx: AuthContext, job_id: str) -> dict[str, list]:
    assert_job_view(db, job_id, ctx)
    rows = db.query(JobIssue).filter(JobIssue.job_id == job_id).order_by(JobIssue.sort_order).all()
    return {
        "issues": [
            {
                "issue_id": i.issue_id,
                "title": i.title,
                "description": i.description,
                "photo_url": i.photo_url,
                "status": _status_str(i.status),
                "estimated_cost": _dec(i.estimated_cost),
            }
            for i in rows
        ]
    }


def quotation_get_api(db: Session, ctx: AuthContext, job_id: str) -> dict[str, Any]:
    assert_job_view(db, job_id, ctx)
    q = db.query(Quotation).filter(Quotation.job_id == job_id).first()
    if q is None:
        raise AppException("No quotation", status_code=404)
    return {
        "quotation_id": q.quotation_id,
        "issues_total": _dec(q.issues_total),
        "labour_charge": _dec(q.labour_charge),
        "discount": _dec(q.discount),
        "total_amount": _dec(q.total_amount),
        "advance_required": _dec(q.advance_required),
        "balance_due": _dec(q.balance_due),
        "customer_accepted": q.customer_accepted,
    }


def quotation_accept_api(db: Session, ctx: AuthContext, *, job_id: str, customer_id: str) -> dict[str, str]:
    job = assert_job_view(db, job_id, ctx)
    if str(job.customer_id) != customer_id or ctx.user_id != customer_id:
        raise AppException("Forbidden", status_code=403)
    q = db.query(Quotation).filter(Quotation.job_id == job_id).first()
    if q is None:
        raise AppException("No quotation", status_code=404)
    q.customer_accepted = True
    q.accepted_at = _now()
    job.status = JobStatusEnum.APPROVED
    # Transparency: log acceptance so admin sees it immediately in chat.
    db.add(
        ChatMessage(
            message_id=str(uuid.uuid4()),
            job_id=job.job_id,
            sender_id=ctx.user_id,
            message_type=MessageTypeEnum.SYSTEM,
            body="Quotation accepted",
            payload={"kind": "quotation_accepted"},
        )
    )
    db.commit()
    return {"message": "Accepted"}


def payment_record_api(
    db: Session,
    ctx: AuthContext,
    *,
    job_id: str,
    payment_type: str,
    amount: float,
    method: str | None,
    reference_no: str | None,
    paid_at: datetime,
) -> dict[str, Any]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    job = get_job(db, job_id)
    if job is None:
        raise AppException("Job not found", status_code=404)
    pay = Payment(
        payment_id=str(uuid.uuid4()),
        job_id=job_id,
        payment_type=payment_type,
        amount=Decimal(str(amount)),
        method=method,
        reference_no=reference_no,
        recorded_by=ctx.user_id,
        paid_at=paid_at,
    )
    db.add(pay)
    if payment_type == "advance":
        job.payment_status = PaymentStatusEnum.ADVANCE_PAID
        job.advance_paid_at = paid_at
    elif payment_type == "final":
        job.payment_status = PaymentStatusEnum.FULLY_PAID
        job.final_paid_at = paid_at
    db.commit()
    return {"payment_id": pay.payment_id}


def stripe_create_payment_intent_api(
    db: Session,
    ctx: AuthContext,
    *,
    job_id: str,
    payment_type: str,
    amount: float,
    currency: str = "sar",
) -> dict[str, Any]:
    """Create Stripe PaymentIntent for card/wallet payment (advance/final)."""
    assert_job_view(db, job_id, ctx)
    if stripe is None:
        raise AppException("Stripe not installed", status_code=500)
    if not settings.STRIPE_SECRET_KEY.strip():
        raise AppException("Stripe not configured", status_code=500)
    if payment_type not in ("advance", "final"):
        raise AppException("Invalid payment_type", status_code=400)
    if amount <= 0:
        raise AppException("Invalid amount", status_code=400)

    job = get_job(db, job_id)
    if job is None:
        raise AppException("Job not found", status_code=404)

    stripe.api_key = settings.STRIPE_SECRET_KEY.strip()
    cents = int(Decimal(str(amount)) * 100)
    pi = stripe.PaymentIntent.create(
        amount=cents,
        currency=currency.lower(),
        automatic_payment_methods={"enabled": True},
        metadata={
            "job_id": job_id,
            "payment_type": payment_type,
            "customer_id": str(job.customer_id),
        },
    )
    return {"payment_intent_id": pi["id"], "client_secret": pi["client_secret"]}


def payments_list_api(db: Session, ctx: AuthContext, job_id: str) -> dict[str, list]:
    assert_job_view(db, job_id, ctx)
    rows = db.query(Payment).filter(Payment.job_id == job_id).all()
    return {
        "payments": [
            {
                "payment_id": p.payment_id,
                "payment_type": p.payment_type,
                "amount": _dec(p.amount),
                "method": p.method,
                "paid_at": p.paid_at.isoformat(),
            }
            for p in rows
        ]
    }


def bays_list_api(db: Session, ctx: AuthContext) -> list[dict[str, Any]]:
    _ = ctx
    rows = db.query(Bay).order_by(Bay.bay_number).all()
    return [
        {
            "bay_id": b.bay_id,
            "bay_number": b.bay_number,
            "bay_name": b.bay_name,
            "status": _status_str(b.status),
        }
        for b in rows
    ]


def bay_create_api(db: Session, ctx: AuthContext, *, bay_number: str, bay_name: str | None) -> dict[str, Any]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    b = Bay(bay_id=str(uuid.uuid4()), bay_number=bay_number, bay_name=bay_name)
    db.add(b)
    db.commit()
    db.refresh(b)
    return {"bay_id": b.bay_id, "bay_number": b.bay_number}


def catalogue_create_api(
    db: Session, ctx: AuthContext, data: dict[str, Any]
) -> dict[str, Any]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    s = ServiceCatalogue(
        service_id=str(uuid.uuid4()),
        name=data["name"],
        description=data.get("description"),
        category=data.get("category"),
        base_price=Decimal(str(data["base_price"])) if data.get("base_price") is not None else None,
        sort_order=int(data.get("sort_order") or 0),
    )
    db.add(s)
    db.commit()
    return {"service_id": s.service_id}


def catalogue_update_api(db: Session, ctx: AuthContext, service_id: str, data: dict[str, Any]) -> dict[str, Any]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    s = db.query(ServiceCatalogue).filter(ServiceCatalogue.service_id == service_id).first()
    if s is None:
        raise AppException("Not found", status_code=404)
    for k in ("name", "description", "category"):
        if k in data and data[k] is not None:
            setattr(s, k, data[k])
    if "base_price" in data and data["base_price"] is not None:
        s.base_price = Decimal(str(data["base_price"]))
    if "sort_order" in data:
        s.sort_order = int(data["sort_order"])
    db.commit()
    return {"service_id": s.service_id}


def catalogue_delete_api(db: Session, ctx: AuthContext, service_id: str) -> dict[str, str]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    s = db.query(ServiceCatalogue).filter(ServiceCatalogue.service_id == service_id).first()
    if s:
        db.delete(s)
        db.commit()
    return {"message": "ok"}


def catalogue_toggle_api(db: Session, ctx: AuthContext, *, service_id: str, is_active: bool) -> dict[str, str]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    s = db.query(ServiceCatalogue).filter(ServiceCatalogue.service_id == service_id).first()
    if s is None:
        raise AppException("Not found", status_code=404)
    s.is_active = is_active
    db.commit()
    return {"message": "ok"}


def sos_create_api(db: Session, ctx: AuthContext, data: dict[str, Any]) -> dict[str, Any]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    t = SosIssueType(
        issue_type_id=str(uuid.uuid4()),
        name=data["name"],
        icon_url=data.get("icon_url"),
        sort_order=int(data.get("sort_order") or 0),
    )
    db.add(t)
    db.commit()
    return {"issue_type_id": t.issue_type_id}


def sos_update_api(db: Session, ctx: AuthContext, issue_type_id: str, data: dict[str, Any]) -> dict[str, str]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    t = db.query(SosIssueType).filter(SosIssueType.issue_type_id == issue_type_id).first()
    if t is None:
        raise AppException("Not found", status_code=404)
    if "name" in data:
        t.name = data["name"]
    if "icon_url" in data:
        t.icon_url = data["icon_url"]
    if "sort_order" in data:
        t.sort_order = int(data["sort_order"])
    db.commit()
    return {"message": "ok"}


def sos_delete_api(db: Session, ctx: AuthContext, issue_type_id: str) -> dict[str, str]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    t = db.query(SosIssueType).filter(SosIssueType.issue_type_id == issue_type_id).first()
    if t:
        db.delete(t)
        db.commit()
    return {"message": "ok"}


def _jobs_in_range(db: Session, from_date: datetime, to_date: datetime):
    return db.query(Job).filter(Job.created_at >= from_date, Job.created_at <= to_date)


def analytics_summary_api(db: Session, ctx: AuthContext, from_date: datetime, to_date: datetime) -> dict[str, Any]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    total_jobs = _jobs_in_range(db, from_date, to_date).count()
    total_sos = _jobs_in_range(db, from_date, to_date).filter(Job.job_type == JobTypeEnum.SOS).count()
    total_service = _jobs_in_range(db, from_date, to_date).filter(Job.job_type == JobTypeEnum.SERVICE).count()
    payments = (
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.paid_at >= from_date, Payment.paid_at <= to_date)
        .scalar()
    )
    return {
        "total_jobs": total_jobs,
        "total_sos": total_sos,
        "total_service": total_service,
        "total_revenue": float(payments or 0),
        "advance_collected": 0.0,
        "balance_due": 0.0,
    }


def analytics_jobs_by_status(
    db: Session, ctx: AuthContext, from_date: datetime, to_date: datetime
) -> dict[str, int]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    rows = (
        db.query(Job.status, func.count())
        .filter(Job.created_at >= from_date, Job.created_at <= to_date)
        .group_by(Job.status)
        .all()
    )
    return {_status_str(s): int(c) for s, c in rows}


def analytics_revenue_trend(
    db: Session, ctx: AuthContext, from_date: datetime, to_date: datetime, granularity: str
) -> list[dict[str, Any]]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    g = (granularity or "day").lower()
    if g not in ("day", "week", "month"):
        raise AppException("Invalid granularity", status_code=400)
    # Postgres: date_trunc. For other DBs, fall back to DATE(paid_at).
    try:
        period = func.date_trunc(g, Payment.paid_at)
    except Exception:  # pragma: no cover
        period = func.date(Payment.paid_at)
    rows = (
        db.query(period.label("period"), func.coalesce(func.sum(Payment.amount), 0).label("revenue"))
        .filter(Payment.paid_at >= from_date, Payment.paid_at <= to_date)
        .group_by("period")
        .order_by("period")
        .all()
    )
    out: list[dict[str, Any]] = []
    for p, rev in rows:
        out.append({"period": p.isoformat() if hasattr(p, "isoformat") else str(p), "revenue": float(rev or 0)})
    return out


def analytics_agent_performance(db: Session, ctx: AuthContext, from_date: datetime, to_date: datetime) -> list[dict[str, Any]]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    # Minimal version: delivered jobs per agent. Pickup time requires more lifecycle timestamps.
    rows = (
        db.query(Job.agent_id, func.count().label("jobs_completed"))
        .filter(Job.created_at >= from_date, Job.created_at <= to_date, Job.agent_id.isnot(None), Job.status == JobStatusEnum.DELIVERED)
        .group_by(Job.agent_id)
        .all()
    )
    return [
        {
            "agent_id": str(agent_id),
            "agent_name": "",
            "jobs_completed": int(cnt),
            "avg_pickup_time_min": None,
        }
        for agent_id, cnt in rows
    ]


def analytics_bay_utilization(db: Session, ctx: AuthContext, from_date: datetime, to_date: datetime) -> list[dict[str, Any]]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    rows = (
        db.query(Job.bay_id, func.count().label("jobs_count"))
        .filter(Job.created_at >= from_date, Job.created_at <= to_date, Job.bay_id.isnot(None))
        .group_by(Job.bay_id)
        .all()
    )
    return [
        {"bay_id": str(bay_id), "bay_number": "", "jobs_count": int(cnt), "avg_days": None}
        for bay_id, cnt in rows
    ]


def analytics_top_services(
    db: Session, ctx: AuthContext, from_date: datetime, to_date: datetime, limit: int
) -> list[dict[str, Any]]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    l = min(max(int(limit), 1), 50)
    rows = (
        db.query(ServiceCatalogue.name, func.count().label("cnt"))
        .join(JobService, JobService.service_id == ServiceCatalogue.service_id)
        .join(Job, Job.job_id == JobService.job_id)
        .filter(Job.created_at >= from_date, Job.created_at <= to_date)
        .group_by(ServiceCatalogue.name)
        .order_by(func.count().desc())
        .limit(l)
        .all()
    )
    return [{"service_name": str(name), "count": int(cnt)} for name, cnt in rows]


def bay_update_api(db: Session, ctx: AuthContext, bay_id: str, data: dict[str, Any]) -> dict[str, str]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    b = db.query(Bay).filter(Bay.bay_id == bay_id).first()
    if b is None:
        raise AppException("Not found", status_code=404)
    if "bay_name" in data:
        b.bay_name = data["bay_name"]
    if "bay_number" in data:
        b.bay_number = data["bay_number"]
    db.commit()
    return {"message": "ok"}


def bay_status_api(db: Session, ctx: AuthContext, *, bay_id: str, status: str) -> dict[str, str]:
    if not _is_staff(ctx):
        raise AppException("Admin only", status_code=403)
    b = db.query(Bay).filter(Bay.bay_id == bay_id).first()
    if b is None:
        raise AppException("Not found", status_code=404)
    b.status = BayStatusEnum(status)
    db.commit()
    return {"message": "ok"}
