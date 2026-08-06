"""Add referral_rewarded column to users table.

Revision ID: 006_referral_rewarded
Revises: 005_referrals_and_custom_interests
"""
from alembic import op
import sqlalchemy as sa

revision = "006_referral_rewarded"
down_revision = "005_ref_custom"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("referral_rewarded", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("users", "referral_rewarded")
