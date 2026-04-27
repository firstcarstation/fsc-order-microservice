"""Demo rows for catalogue, SOS types, and bays (optional local dev)."""

import uuid
from alembic import op
import sqlalchemy as sa


revision = "002_seed"
down_revision = "001_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    catalogue = sa.table(
        "service_catalogue",
        sa.column("service_id", sa.String),
        sa.column("name", sa.Text),
        sa.column("description", sa.Text),
        sa.column("category", sa.Text),
        sa.column("base_price", sa.Numeric),
        sa.column("is_active", sa.Boolean),
        sa.column("sort_order", sa.Integer),
    )
    conn.execute(
        sa.insert(catalogue).values(
            service_id=str(uuid.uuid4()),
            name="Oil change",
            description="Engine oil and filter",
            category="Mechanical",
            base_price=49.99,
            is_active=True,
            sort_order=1,
        )
    )
    sos = sa.table(
        "sos_issue_types",
        sa.column("issue_type_id", sa.String),
        sa.column("name", sa.Text),
        sa.column("icon_url", sa.Text),
        sa.column("is_active", sa.Boolean),
        sa.column("sort_order", sa.Integer),
    )
    conn.execute(
        sa.insert(sos).values(
            issue_type_id=str(uuid.uuid4()),
            name="Flat tyre",
            icon_url=None,
            is_active=True,
            sort_order=1,
        )
    )
    bays = sa.table(
        "bays",
        sa.column("bay_id", sa.String),
        sa.column("bay_number", sa.String),
        sa.column("bay_name", sa.Text),
        sa.column("status", sa.String),
    )
    conn.execute(
        sa.insert(bays).values(
            bay_id=str(uuid.uuid4()),
            bay_number="BAY-01",
            bay_name="Main",
            status="free",
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM bays WHERE bay_number = 'BAY-01'"))
    conn.execute(sa.text("DELETE FROM sos_issue_types WHERE name = 'Flat tyre'"))
    conn.execute(sa.text("DELETE FROM service_catalogue WHERE name = 'Oil change'"))
