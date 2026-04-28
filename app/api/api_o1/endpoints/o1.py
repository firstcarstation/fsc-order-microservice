from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_current_user, require_admin
from app.core.database.dependency import get_db
from app.services import operations as op

router = APIRouter()

@router.get("/garage/settings")
def garage_settings_get(db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)):
    return op.garage_settings_get_api(db, ctx)


@router.put("/garage/settings")
def garage_settings_update(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)):
    return op.garage_settings_update_api(db, ctx, payload)


# --- Jobs ---
@router.post("/jobs/create-sos")
def jobs_create_sos(
    payload: dict,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_current_user),
):
    return op.create_sos_job(
        db,
        ctx,
        customer_id=payload["customer_id"],
        vehicle_id=payload["vehicle_id"],
        pickup_lat=float(payload["pickup_lat"]),
        pickup_lng=float(payload["pickup_lng"]),
        pickup_address=payload["pickup_address"],
        sos_issue_type_ids=list(payload.get("sos_issue_type_ids") or []),
        customer_note=payload.get("customer_note"),
    )


@router.post("/jobs/create-service")
def jobs_create_service(
    payload: dict,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_current_user),
):
    return op.create_service_job(
        db,
        ctx,
        customer_id=payload["customer_id"],
        vehicle_id=payload["vehicle_id"],
        service_ids=list(payload.get("service_ids") or []),
        scheduled_at=datetime.fromisoformat(payload["scheduled_at"]) if payload.get("scheduled_at") else None,
        pickup_lat=float(payload["pickup_lat"]),
        pickup_lng=float(payload["pickup_lng"]),
        pickup_address=str(payload.get("pickup_address") or "Scheduled service"),
        customer_note=payload.get("customer_note"),
    )


@router.post("/jobs/admin-create-ticket")
def jobs_admin_create_ticket(
    payload: dict,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
):
    """Create a workshop ticket from the admin app (vehicle already at garage)."""
    return op.create_admin_ticket_job(
        db,
        ctx,
        customer_id=payload["customer_id"],
        vehicle_id=payload["vehicle_id"],
        service_ids=list(payload.get("service_ids") or []),
        vehicle_model=payload.get("vehicle_model"),
        plate_number=payload.get("plate_number"),
        vin_number=payload.get("vin_number"),
        admin_note=payload.get("admin_note"),
    )


@router.post("/jobs/list")
def jobs_list(
    payload: dict,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_current_user),
):
    return op.list_jobs_api(
        db,
        ctx,
        customer_id=payload.get("customer_id"),
        agent_id=payload.get("agent_id"),
        status=payload.get("status"),
        page=int(payload.get("page") or 1),
        limit=int(payload.get("limit") or 20),
    )


@router.post("/jobs/details")
def jobs_details(
    payload: dict,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_current_user),
):
    return op.job_details_api(db, ctx, payload["job_id"])


@router.put("/jobs/update-status")
def jobs_update_status(
    payload: dict,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_current_user),
):
    return op.update_job_status_api(
        db,
        ctx,
        job_id=payload["job_id"],
        status=payload["status"],
        note=payload.get("note"),
        agent_lat=float(payload["agent_lat"]) if payload.get("agent_lat") is not None else None,
        agent_lng=float(payload["agent_lng"]) if payload.get("agent_lng") is not None else None,
    )


@router.post("/jobs/claim")
def jobs_claim(
    payload: dict,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_current_user),
):
    return op.claim_job_api(
        db,
        ctx,
        job_id=payload["job_id"],
        agent_lat=float(payload["agent_lat"]) if payload.get("agent_lat") is not None else None,
        agent_lng=float(payload["agent_lng"]) if payload.get("agent_lng") is not None else None,
    )


@router.post("/jobs/assign-agent")
def jobs_assign_agent(
    payload: dict,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
):
    return op.assign_agent_api(db, ctx, job_id=payload["job_id"], agent_id=payload["agent_id"])


@router.post("/jobs/schedule-delivery")
def jobs_schedule_delivery(
    payload: dict,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
):
    return op.schedule_delivery_api(
        db,
        ctx,
        job_id=payload["job_id"],
        driver_id=payload["driver_id"],
        scheduled_at=datetime.fromisoformat(payload["scheduled_at"]),
        note=payload.get("note"),
    )


@router.post("/jobs/start-delivery")
def jobs_start_delivery(
    payload: dict,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_current_user),
):
    return op.start_delivery_api(db, ctx, job_id=payload["job_id"])


@router.post("/jobs/assign-bay")
def jobs_assign_bay(
    payload: dict,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
):
    return op.assign_bay_api(db, ctx, job_id=payload["job_id"], bay_id=payload["bay_id"])


@router.post("/jobs/assign-technician")
def jobs_assign_technician(
    payload: dict,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
):
    return op.assign_technician_api(db, ctx, job_id=payload["job_id"], technician_id=payload.get("technician_id"))


@router.post("/jobs/cancel")
def jobs_cancel(
    payload: dict,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_current_user),
):
    return op.cancel_job_api(db, ctx, job_id=payload["job_id"], reason=payload.get("reason") or "")


@router.put("/jobs/set-delivery-location")
def jobs_set_delivery_location(
    payload: dict,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_current_user),
):
    return op.set_delivery_location_api(
        db,
        ctx,
        job_id=payload["job_id"],
        delivery_address=payload.get("delivery_address") or "",
        delivery_lat=payload.get("delivery_lat"),
        delivery_lng=payload.get("delivery_lng"),
    )


@router.post("/jobs/upload-photo")
def jobs_upload_photo(
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_current_user),
    job_id: str = Form(...),
    stage: str = Form(...),
    caption: str | None = Form(None),
    photo: UploadFile = File(...),
):
    raw = photo.file.read()
    return op.save_job_photo(
        db, ctx, job_id=job_id, stage=stage, file_bytes=raw, filename=photo.filename or "p.jpg", caption=caption
    )


@router.get("/jobs/{job_id}/photos")
def jobs_photos_get(
    job_id: str,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_current_user),
    stage: str | None = Query(None),
):
    return op.list_job_photos_api(db, ctx, job_id, stage)


# --- Catalogue (public read) ---
@router.get("/catalogue")
def catalogue_list(db: Session = Depends(get_db)):
    return op.catalogue_list_public(db)


@router.get("/catalogue/admin")
def catalogue_list_admin(db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)):
    return op.catalogue_list_admin(db, ctx)


@router.post("/catalogue/create")
def catalogue_create(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)):
    return op.catalogue_create_api(db, ctx, payload)


@router.put("/catalogue/update")
def catalogue_update(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)):
    return op.catalogue_update_api(db, ctx, payload["service_id"], payload)


@router.post("/catalogue/delete")
def catalogue_delete(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)):
    return op.catalogue_delete_api(db, ctx, payload["service_id"])


@router.post("/catalogue/toggle")
def catalogue_toggle(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)):
    return op.catalogue_toggle_api(db, ctx, service_id=payload["service_id"], is_active=bool(payload["is_active"]))


# --- SOS issue types ---
@router.get("/sos-issues")
def sos_list(db: Session = Depends(get_db)):
    return op.sos_issues_list_public(db)


@router.post("/sos-issues/create")
def sos_create(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)):
    return op.sos_create_api(db, ctx, payload)


@router.put("/sos-issues/update")
def sos_update(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)):
    return op.sos_update_api(db, ctx, payload["issue_type_id"], payload)


@router.post("/sos-issues/delete")
def sos_delete(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)):
    return op.sos_delete_api(db, ctx, payload["issue_type_id"])


# --- Chat ---
@router.post("/chat/send")
def chat_send(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    return op.chat_send_api(
        db,
        ctx,
        job_id=payload["job_id"],
        sender_id=payload["sender_id"],
        message_type=payload["message_type"],
        body=payload.get("body"),
        payload=payload.get("payload"),
    )


@router.post("/chat/history")
def chat_history(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    return op.chat_history_api(
        db, ctx, job_id=payload["job_id"], page=int(payload.get("page") or 1), limit=int(payload.get("limit") or 50)
    )


@router.post("/chat/mark-read")
def chat_mark_read(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    return op.chat_mark_read_api(db, ctx, job_id=payload["job_id"], reader_id=payload["reader_id"])


@router.post("/chat/send-issue-list")
def chat_send_issues(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)):
    return op.send_issue_list_api(db, ctx, job_id=payload["job_id"], issues=list(payload.get("issues") or []))


@router.post("/chat/send-quotation")
def chat_send_quote(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)):
    return op.send_quotation_api(
        db,
        ctx,
        job_id=payload["job_id"],
        labour_charge=float(payload["labour_charge"]),
        discount=float(payload["discount"]) if payload.get("discount") is not None else None,
        advance_required=float(payload["advance_required"]) if payload.get("advance_required") is not None else None,
    )


# --- Issues ---
@router.post("/issues/respond")
def issues_respond(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    return op.issues_respond_api(db, ctx, job_id=payload["job_id"], responses=list(payload.get("responses") or []))


@router.get("/issues/{job_id}")
def issues_for_job(job_id: str, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    return op.issues_list_api(db, ctx, job_id)


# --- Quotation & payments ---
@router.get("/quotation/{job_id}")
def quotation_get(job_id: str, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    return op.quotation_get_api(db, ctx, job_id)


@router.post("/quotation/accept")
def quotation_accept(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    return op.quotation_accept_api(db, ctx, job_id=payload["job_id"], customer_id=payload["customer_id"])


@router.post("/payments/record")
def payment_record(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)):
    paid_at = datetime.fromisoformat(payload["paid_at"]) if isinstance(payload["paid_at"], str) else payload["paid_at"]
    return op.payment_record_api(
        db,
        ctx,
        job_id=payload["job_id"],
        payment_type=payload["payment_type"],
        amount=float(payload["amount"]),
        method=payload.get("method"),
        reference_no=payload.get("reference_no"),
        paid_at=paid_at,
    )


@router.get("/payments/{job_id}")
def payments_list(job_id: str, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    return op.payments_list_api(db, ctx, job_id)

@router.post("/payments/stripe/create-intent")
def payments_stripe_create_intent(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    return op.stripe_create_payment_intent_api(
        db,
        ctx,
        job_id=payload["job_id"],
        payment_type=payload["payment_type"],
        amount=float(payload["amount"]),
        currency=str(payload.get("currency") or "sar"),
    )


# --- Bays ---
@router.get("/bays")
def bays_list(db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    return op.bays_list_api(db, ctx)


@router.post("/bays/create")
def bays_create(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)):
    return op.bay_create_api(db, ctx, bay_number=payload["bay_number"], bay_name=payload.get("bay_name"))


@router.put("/bays/update")
def bays_update(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)):
    return op.bay_update_api(db, ctx, payload["bay_id"], payload)


@router.post("/bays/update-status")
def bays_status(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)):
    return op.bay_status_api(db, ctx, bay_id=payload["bay_id"], status=payload["status"])


# --- Technicians (lookup) ---
@router.get("/technicians")
def tech_list(db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)):
    return op.technicians_list_api(db, ctx)


@router.post("/technicians/create")
def tech_create(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)):
    return op.technician_create_api(db, ctx, name=payload["name"], sort_order=int(payload.get("sort_order") or 0))


@router.put("/technicians/update")
def tech_update(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)):
    return op.technician_update_api(db, ctx, payload["technician_id"], payload)


@router.post("/technicians/toggle")
def tech_toggle(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)):
    return op.technician_toggle_api(db, ctx, technician_id=payload["technician_id"], is_active=bool(payload["is_active"]))


@router.post("/technicians/delete")
def tech_delete(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_admin)):
    return op.technician_delete_api(db, ctx, payload["technician_id"])


# --- Tracking ---
@router.post("/tracking/update")
def tracking_update(payload: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    return op.tracking_update_api(
        db,
        ctx,
        job_id=payload["job_id"],
        agent_id=payload["agent_id"],
        lat=float(payload["lat"]),
        lng=float(payload["lng"]),
        heading=float(payload["heading"]) if payload.get("heading") is not None else None,
        speed_kmh=float(payload["speed_kmh"]) if payload.get("speed_kmh") is not None else None,
        agent_name=str(payload.get("agent_name") or ""),
    )


@router.get("/tracking/latest/{job_id}")
def tracking_latest(job_id: str, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_current_user)):
    return op.tracking_latest_api(db, ctx, job_id)


# --- Analytics ---
@router.get("/analytics/summary")
def analytics_summary(
    from_date: datetime = Query(...),
    to_date: datetime = Query(...),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
):
    return op.analytics_summary_api(db, ctx, from_date, to_date)


@router.get("/analytics/jobs-by-status")
def analytics_by_status(
    from_date: datetime = Query(...),
    to_date: datetime = Query(...),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
):
    return op.analytics_jobs_by_status(db, ctx, from_date, to_date)


@router.get("/analytics/revenue-trend")
def analytics_revenue_trend(
    from_date: datetime = Query(...),
    to_date: datetime = Query(...),
    granularity: str = Query("day"),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
):
    return op.analytics_revenue_trend(db, ctx, from_date, to_date, granularity)


@router.get("/analytics/agent-performance")
def analytics_agent_performance(
    from_date: datetime = Query(...),
    to_date: datetime = Query(...),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
):
    return op.analytics_agent_performance(db, ctx, from_date, to_date)


@router.get("/analytics/bay-utilization")
def analytics_bay_utilization(
    from_date: datetime = Query(...),
    to_date: datetime = Query(...),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
):
    return op.analytics_bay_utilization(db, ctx, from_date, to_date)


@router.get("/analytics/top-services")
def analytics_top_services(
    from_date: datetime = Query(...),
    to_date: datetime = Query(...),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
):
    return op.analytics_top_services(db, ctx, from_date, to_date, limit)
