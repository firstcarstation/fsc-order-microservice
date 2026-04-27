"""Add job_issues.photo_url for admin issue photos."""

from alembic import op
import sqlalchemy as sa


revision = "003_issue_photo"
down_revision = "002_seed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_issues", sa.Column("photo_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("job_issues", "photo_url")
