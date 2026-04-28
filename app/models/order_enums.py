from enum import Enum as PyEnum


class JobTypeEnum(str, PyEnum):
    SOS = "sos"
    SERVICE = "service"


class JobStatusEnum(str, PyEnum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    AGENT_EN_ROUTE = "agent_en_route"
    AGENT_ARRIVED = "agent_arrived"
    VEHICLE_PICKED_UP = "vehicle_picked_up"
    IN_TRANSIT_TO_GARAGE = "in_transit_to_garage"
    AT_GARAGE = "at_garage"
    UNDER_INSPECTION = "under_inspection"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    IN_REPAIR = "in_repair"
    REPAIR_COMPLETE = "repair_complete"
    READY_FOR_DELIVERY = "ready_for_delivery"
    # Admin assigned driver + time; agent must tap "Start delivery" before en route.
    DELIVERY_SCHEDULED = "delivery_scheduled"
    OUT_FOR_DELIVERY = "out_for_delivery"
    # Agent at customer drop-off; delivery photos + mark delivered follow.
    DELIVERY_ARRIVED = "delivery_arrived"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class PhotoStageEnum(str, PyEnum):
    PICKUP_BEFORE = "pickup_before"
    PICKUP_AFTER = "pickup_after"
    GARAGE_ARRIVAL = "garage_arrival"
    REPAIR_COMPLETE = "repair_complete"
    DELIVERY = "delivery"
    ISSUE_ATTACHMENT = "issue_attachment"
    RECEIPT = "receipt"


class IssueStatusEnum(str, PyEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PaymentStatusEnum(str, PyEnum):
    UNPAID = "unpaid"
    ADVANCE_PAID = "advance_paid"
    FULLY_PAID = "fully_paid"
    REFUNDED = "refunded"


class MessageTypeEnum(str, PyEnum):
    TEXT = "text"
    ISSUE_LIST = "issue_list"
    QUOTATION = "quotation"
    IMAGE = "image"  # legacy
    PHOTO = "photo"
    SYSTEM = "system"


class BayStatusEnum(str, PyEnum):
    FREE = "free"
    OCCUPIED = "occupied"
    RESERVED = "reserved"
    MAINTENANCE = "maintenance"
