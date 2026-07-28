"""Add referrer_id to users and custom_interests to profiles.

Revision ID: 005_referrals_and_custom_interests
Revises: 004_seed_test_profiles
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa

revision = "005_referrals_and_custom_interests"
down_revision = "004_seed_test_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("referrer_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("profiles", sa.Column("custom_interests", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("profiles", "custom_interests")
    op.drop_column("users", "referrer_id")
