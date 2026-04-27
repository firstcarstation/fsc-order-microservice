"""Add garage settings table.

Revision ID: 007_garage_settings
Revises: 006_job_customer_snapshot
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_garage_settings"
down_revision: Union[str, Sequence[str], None] = "006_job_customer_snapshot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "garage_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("address_line_1", sa.Text(), nullable=True),
        sa.Column("lat", sa.Numeric(10, 7), nullable=True),
        sa.Column("lng", sa.Numeric(10, 7), nullable=True),
        sa.Column("contact_name", sa.Text(), nullable=True),
        sa.Column("contact_phone", sa.String(length=20), nullable=True),
        sa.Column("contact_email", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    # Seed row
    op.execute("INSERT INTO garage_settings (id) VALUES (1)")


def downgrade() -> None:
    op.drop_table("garage_settings")

