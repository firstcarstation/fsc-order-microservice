"""Initial order_db schema per First Car Station spec."""

from alembic import op
import sqlalchemy as sa


revision = "001_order"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_catalogue",
        sa.Column("service_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("base_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "sos_issue_types",
        sa.Column("issue_type_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("icon_url", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "bays",
        sa.Column("bay_id", sa.String(36), primary_key=True),
        sa.Column("bay_number", sa.String(20), nullable=False),
        sa.Column("bay_name", sa.Text(), nullable=True),
        sa.Column("status", sa.String(64), nullable=False, server_default="free"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("uq_bays_bay_number", "bays", ["bay_number"], unique=True)

    op.create_table(
        "jobs",
        sa.Column("job_id", sa.String(36), primary_key=True),
        sa.Column("job_number", sa.String(32), nullable=False),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(64), nullable=False, server_default="pending"),
        sa.Column("customer_id", sa.String(36), nullable=False),
        sa.Column("agent_id", sa.String(36), nullable=True),
        sa.Column("vehicle_id", sa.String(36), nullable=False),
        sa.Column("bay_id", sa.String(36), sa.ForeignKey("bays.bay_id", ondelete="SET NULL"), nullable=True),
        sa.Column("pickup_address", sa.Text(), nullable=False),
        sa.Column("pickup_lat", sa.Numeric(10, 7), nullable=False),
        sa.Column("pickup_lng", sa.Numeric(10, 7), nullable=False),
        sa.Column("garage_lat", sa.Numeric(10, 7), nullable=True),
        sa.Column("garage_lng", sa.Numeric(10, 7), nullable=True),
        sa.Column("sos_issue_type_ids", sa.JSON(), nullable=True),
        sa.Column("customer_note", sa.Text(), nullable=True),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("payment_status", sa.String(64), nullable=False, server_default="unpaid"),
        sa.Column("advance_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("final_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("labour_charge", sa.Numeric(10, 2), nullable=True),
        sa.Column("advance_paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("final_paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("picked_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("garage_arrived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_jobs_customer_id", "jobs", ["customer_id"])
    op.create_index("ix_jobs_agent_id", "jobs", ["agent_id"])
    op.create_index("ix_jobs_vehicle_id", "jobs", ["vehicle_id"])
    op.create_index("uq_jobs_job_number", "jobs", ["job_number"], unique=True)

    op.create_table(
        "job_services",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False),
        sa.Column("service_id", sa.String(36), sa.ForeignKey("service_catalogue.service_id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "job_issues",
        sa.Column("issue_id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(10, 2), nullable=True),
        sa.Column("status", sa.String(64), nullable=False, server_default="pending"),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "job_photos",
        sa.Column("photo_id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("photo_url", sa.Text(), nullable=False),
        sa.Column("uploaded_by", sa.String(36), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "job_location_logs",
        sa.Column("log_id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.String(36), nullable=False),
        sa.Column("lat", sa.Numeric(10, 7), nullable=False),
        sa.Column("lng", sa.Numeric(10, 7), nullable=False),
        sa.Column("heading", sa.Numeric(5, 2), nullable=True),
        sa.Column("speed_kmh", sa.Numeric(6, 2), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_job_location_logs_agent_id", "job_location_logs", ["agent_id"])

    op.create_table(
        "chat_messages",
        sa.Column("message_id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_id", sa.String(36), nullable=False),
        sa.Column("message_type", sa.String(64), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_chat_messages_sender_id", "chat_messages", ["sender_id"])

    op.create_table(
        "quotations",
        sa.Column("quotation_id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("issues_total", sa.Numeric(10, 2), nullable=False),
        sa.Column("labour_charge", sa.Numeric(10, 2), nullable=False),
        sa.Column("discount", sa.Numeric(10, 2), nullable=True),
        sa.Column("total_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("advance_required", sa.Numeric(10, 2), nullable=False),
        sa.Column("balance_due", sa.Numeric(10, 2), nullable=False),
        sa.Column("customer_accepted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "payments",
        sa.Column("payment_id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False),
        sa.Column("payment_type", sa.String(32), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("method", sa.String(64), nullable=True),
        sa.Column("reference_no", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.String(36), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("payments")
    op.drop_table("quotations")
    op.drop_table("chat_messages")
    op.drop_table("job_location_logs")
    op.drop_table("job_photos")
    op.drop_table("job_issues")
    op.drop_table("job_services")
    op.drop_table("jobs")
    op.drop_table("bays")
    op.drop_table("sos_issue_types")
    op.drop_table("service_catalogue")
