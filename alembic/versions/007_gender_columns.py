"""Add gender and target_gender columns to profiles table.

Revision ID: 007_gender_columns
Revises: 006_referral_rewarded
"""
from alembic import op
import sqlalchemy as sa

revision = "007_gender_columns"
down_revision = "006_referral_rewarded"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("gender", sa.String(length=20), nullable=True))
    op.add_column("profiles", sa.Column("target_gender", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("profiles", "target_gender")
    op.drop_column("profiles", "gender")
