import uuid

from sqlalchemy import (
    Boolean,
    Column,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime

from app.core.database.base import Base
from app.models.order_enums import (
    BayStatusEnum,
    IssueStatusEnum,
    JobStatusEnum,
    JobTypeEnum,
    MessageTypeEnum,
    PaymentStatusEnum,
    PhotoStageEnum,
)


def _enum(cls):
    return SAEnum(cls, native_enum=False, values_callable=lambda x: [e.value for e in x])


class ServiceCatalogue(Base):
    __tablename__ = "service_catalogue"

    service_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    category = Column(Text, nullable=True)
    base_price = Column(Numeric(10, 2), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())


class SosIssueType(Base):
    __tablename__ = "sos_issue_types"

    issue_type_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(Text, nullable=False)
    icon_url = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())


class Bay(Base):
    __tablename__ = "bays"

    bay_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    bay_number = Column(String(20), nullable=False, unique=True)
    bay_name = Column(Text, nullable=True)
    status = Column(_enum(BayStatusEnum), nullable=False, default=BayStatusEnum.FREE)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())


class Technician(Base):
    __tablename__ = "technicians"

    technician_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())


class GarageSettings(Base):
    __tablename__ = "garage_settings"

    id = Column(Integer, primary_key=True, default=1)
    address_line_1 = Column(Text, nullable=True)
    lat = Column(Numeric(10, 7), nullable=True)
    lng = Column(Numeric(10, 7), nullable=True)
    contact_name = Column(Text, nullable=True)
    contact_phone = Column(String(20), nullable=True)
    contact_email = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class Job(Base):
    __tablename__ = "jobs"

    job_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_number = Column(String(32), nullable=False, unique=True)
    job_type = Column(_enum(JobTypeEnum), nullable=False)
    status = Column(_enum(JobStatusEnum), nullable=False, default=JobStatusEnum.PENDING)
    customer_id = Column(String(36), nullable=False, index=True)
    customer_name = Column(Text, nullable=True)
    customer_mobile_no = Column(String(15), nullable=True)
    agent_id = Column(String(36), nullable=True, index=True)
    vehicle_id = Column(String(36), nullable=False, index=True)
    bay_id = Column(String(36), ForeignKey("bays.bay_id", ondelete="SET NULL"), nullable=True)
    technician_id = Column(String(36), ForeignKey("technicians.technician_id", ondelete="SET NULL"), nullable=True)
    pickup_address = Column(Text, nullable=False)
    pickup_lat = Column(Numeric(10, 7), nullable=False)
    pickup_lng = Column(Numeric(10, 7), nullable=False)
    garage_lat = Column(Numeric(10, 7), nullable=True)
    garage_lng = Column(Numeric(10, 7), nullable=True)
    sos_issue_type_ids = Column(JSON, nullable=True)
    customer_note = Column(Text, nullable=True)
    admin_note = Column(Text, nullable=True)
    payment_status = Column(_enum(PaymentStatusEnum), nullable=False, default=PaymentStatusEnum.UNPAID)
    advance_amount = Column(Numeric(10, 2), nullable=True)
    final_amount = Column(Numeric(10, 2), nullable=True)
    labour_charge = Column(Numeric(10, 2), nullable=True)
    advance_paid_at = Column(DateTime(timezone=True), nullable=True)
    final_paid_at = Column(DateTime(timezone=True), nullable=True)
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    eta_minutes = Column(Integer, nullable=True)
    eta_distance_km = Column(Numeric(8, 2), nullable=True)
    eta_updated_at = Column(DateTime(timezone=True), nullable=True)
    picked_up_at = Column(DateTime(timezone=True), nullable=True)
    garage_arrived_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    delivery_address = Column(Text, nullable=True)
    delivery_lat = Column(Numeric(10, 7), nullable=True)
    delivery_lng = Column(Numeric(10, 7), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    job_services = relationship("JobService", back_populates="job", cascade="all, delete-orphan")
    job_issues = relationship("JobIssue", back_populates="job", cascade="all, delete-orphan")
    job_photos = relationship("JobPhoto", back_populates="job", cascade="all, delete-orphan")
    chat_messages = relationship("ChatMessage", back_populates="job", cascade="all, delete-orphan")
    quotation = relationship("Quotation", back_populates="job", uselist=False, cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="job", cascade="all, delete-orphan")


class JobService(Base):
    __tablename__ = "job_services"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False)
    service_id = Column(String(36), ForeignKey("service_catalogue.service_id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    job = relationship("Job", back_populates="job_services")


class JobIssue(Base):
    __tablename__ = "job_issues"

    issue_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    photo_url = Column(Text, nullable=True)
    estimated_cost = Column(Numeric(10, 2), nullable=True)
    status = Column(_enum(IssueStatusEnum), nullable=False, default=IssueStatusEnum.PENDING)
    responded_at = Column(DateTime(timezone=True), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    job = relationship("Job", back_populates="job_issues")


class JobPhoto(Base):
    __tablename__ = "job_photos"

    photo_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False)
    stage = Column(_enum(PhotoStageEnum), nullable=False)
    photo_url = Column(Text, nullable=False)
    uploaded_by = Column(String(36), nullable=False)
    caption = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    job = relationship("Job", back_populates="job_photos")


class JobLocationLog(Base):
    __tablename__ = "job_location_logs"

    log_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(String(36), nullable=False, index=True)
    lat = Column(Numeric(10, 7), nullable=False)
    lng = Column(Numeric(10, 7), nullable=False)
    heading = Column(Numeric(5, 2), nullable=True)
    speed_kmh = Column(Numeric(6, 2), nullable=True)
    captured_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    message_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False)
    sender_id = Column(String(36), nullable=False, index=True)
    message_type = Column(_enum(MessageTypeEnum), nullable=False)
    body = Column(Text, nullable=True)
    payload = Column(JSON, nullable=True)
    is_read = Column(Boolean, nullable=False, default=False)
    read_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    job = relationship("Job", back_populates="chat_messages")


class Quotation(Base):
    __tablename__ = "quotations"

    quotation_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False, unique=True)
    issues_total = Column(Numeric(10, 2), nullable=False)
    labour_charge = Column(Numeric(10, 2), nullable=False)
    discount = Column(Numeric(10, 2), nullable=True)
    total_amount = Column(Numeric(10, 2), nullable=False)
    advance_required = Column(Numeric(10, 2), nullable=False)
    balance_due = Column(Numeric(10, 2), nullable=False)
    customer_accepted = Column(Boolean, nullable=False, default=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    job = relationship("Job", back_populates="quotation")


class Payment(Base):
    __tablename__ = "payments"

    payment_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(36), ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False)
    payment_type = Column(String(32), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    method = Column(String(64), nullable=True)
    reference_no = Column(Text, nullable=True)
    recorded_by = Column(String(36), nullable=False)
    paid_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    job = relationship("Job", back_populates="payments")
