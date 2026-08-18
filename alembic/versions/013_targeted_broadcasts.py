"""Add targeting and scheduling fields to broadcast_logs table

Revision ID: 013_targeted_broadcasts
Revises: 012_fake_users
"""
from alembic import op
import sqlalchemy as sa

revision = "013_targeted_broadcasts"
down_revision = "012_fake_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("broadcast_logs", sa.Column("target_filters", sa.Text(), nullable=True))
    op.add_column("broadcast_logs", sa.Column("photo_url", sa.String(length=300), nullable=True))
    op.add_column("broadcast_logs", sa.Column("button_text", sa.String(length=100), nullable=True))
    op.add_column("broadcast_logs", sa.Column("button_url", sa.String(length=500), nullable=True))
    op.add_column("broadcast_logs", sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("broadcast_logs", sa.Column("status", sa.String(length=20), nullable=False, server_default="completed"))


def downgrade() -> None:
    op.drop_column("broadcast_logs", "status")
    op.drop_column("broadcast_logs", "scheduled_at")
    op.drop_column("broadcast_logs", "button_url")
    op.drop_column("broadcast_logs", "button_text")
    op.drop_column("broadcast_logs", "photo_url")
    op.drop_column("broadcast_logs", "target_filters")
