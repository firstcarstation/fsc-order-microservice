"""Add ETA fields on jobs.

Revision ID: 005_job_eta
Revises: 004_techs
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_job_eta"
down_revision: Union[str, Sequence[str], None] = "004_techs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("eta_minutes", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("eta_distance_km", sa.Numeric(8, 2), nullable=True))
    op.add_column("jobs", sa.Column("eta_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "eta_updated_at")
    op.drop_column("jobs", "eta_distance_km")
    op.drop_column("jobs", "eta_minutes")

