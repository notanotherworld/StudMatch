"""Add is_fake and auto_match_mode to users table

Revision ID: 012_fake_users
Revises: 011_dual_profiles
"""
from alembic import op
import sqlalchemy as sa

revision = "012_fake_users"
down_revision = "011_dual_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_fake", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("users", sa.Column("auto_match_mode", sa.String(length=20), nullable=True, server_default="instant"))


def downgrade() -> None:
    op.drop_column("users", "auto_match_mode")
    op.drop_column("users", "is_fake")
