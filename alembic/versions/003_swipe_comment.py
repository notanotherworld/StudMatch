"""Add comment column to swipes table.

Revision ID: 003_swipe_comment
Revises: 002_reports_broadcasts
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa

revision = "003_swipe_comment"
down_revision = "002_reports_broadcasts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("swipes", sa.Column("comment", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("swipes", "comment")
