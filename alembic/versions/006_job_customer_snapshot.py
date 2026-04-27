"""Add customer snapshot fields on jobs.

Revision ID: 006_job_customer_snapshot
Revises: 005_job_eta
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_job_customer_snapshot"
down_revision: Union[str, Sequence[str], None] = "005_job_eta"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("customer_name", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("customer_mobile_no", sa.String(length=15), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "customer_mobile_no")
    op.drop_column("jobs", "customer_name")

