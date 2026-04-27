"""Add technicians table and technician_id on jobs.

Revision ID: 004_techs
Revises: 003_issue_photo
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_techs"
down_revision: Union[str, Sequence[str], None] = "003_issue_photo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "technicians",
        sa.Column("technician_id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("jobs", sa.Column("technician_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_jobs_technician_id",
        "jobs",
        "technicians",
        ["technician_id"],
        ["technician_id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_jobs_technician_id", "jobs", type_="foreignkey")
    op.drop_column("jobs", "technician_id")
    op.drop_table("technicians")

