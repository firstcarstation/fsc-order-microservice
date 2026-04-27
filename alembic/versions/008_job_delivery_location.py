"""Add job delivery location fields.

Revision ID: 008_job_delivery_location
Revises: 007_garage_settings
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_job_delivery_location"
down_revision: Union[str, Sequence[str], None] = "007_garage_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("delivery_address", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("delivery_lat", sa.Numeric(10, 7), nullable=True))
    op.add_column("jobs", sa.Column("delivery_lng", sa.Numeric(10, 7), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "delivery_lng")
    op.drop_column("jobs", "delivery_lat")
    op.drop_column("jobs", "delivery_address")

